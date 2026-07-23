from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from whisperflow_local.__main__ import SAMPLE, ensure_sample, load_wav_16k_mono
from whisperflow_local.cleanup import Cleaner
from whisperflow_local.config import load_config
from whisperflow_local.evaluation import guarded_cleanup
from whisperflow_local.inserter import FocusTarget, Inserter, capture_focus_target
from whisperflow_local.performance_profiles import resolve_profile
from whisperflow_local.service import LocalServiceManager, ServiceState
from whisperflow_local.stt import Transcriber


class InsertionAdapter(Protocol):
    def capture_target(self) -> FocusTarget: ...
    def insert(self, text: str, target: FocusTarget) -> tuple[bool, str]: ...


class LiveInsertionAdapter:
    """Adapter for an explicitly requested real focus-checked paste benchmark."""

    def __init__(self, cfg: dict) -> None:
        self._inserter = Inserter(cfg)

    def capture_target(self) -> FocusTarget:
        return capture_focus_target()

    def insert(self, text: str, target: FocusTarget) -> tuple[bool, str]:
        return self._inserter.insert(text, target)


class _EphemeralSecretStore:
    """Keep benchmark service credentials process-local."""

    def set(self, account: str, value: str) -> None:
        return None


def resolved_stt_config(cfg) -> dict:
    performance = cfg.performance
    profile = resolve_profile(str(performance.get("profile", "instant")))
    resolved = dict(cfg.stt)
    resolved["model"] = profile.model
    resolved["batch_size"] = profile.batch_size
    return resolved


def managed_cleanup_config(cleanup: dict) -> dict:
    """Prevent Cleaner from resolving credentials outside the service manager."""
    resolved = dict(cleanup)
    for key in (
        "fallback_provider",
        "api_key_env",
        "api_key",
        "api_key_keychain_account",
    ):
        resolved.pop(key, None)
    return resolved


def connect_owned_cleanup_service(manager: LocalServiceManager) -> str:
    health = manager.connect_or_start()
    if (
        health.state is not ServiceState.READY
        or not health.owned
        or not health.api_key
    ):
        raise RuntimeError(
            "benchmark requires a ready app-owned cleanup service "
            f"(state={health.state.value}, owned={health.owned})"
        )
    return health.api_key


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values); position = (len(ordered) - 1) * fraction
    lower = int(position); upper = min(lower + 1, len(ordered) - 1); weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values: list[float]) -> dict[str, float]:
    return {"p50_ms": round(statistics.median(values), 1), "p95_ms": round(percentile(values, .95), 1),
            "min_ms": round(min(values), 1), "max_ms": round(max(values), 1)}


def peak_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS and KiB on common Unix variants.
    return round(value / (1024 * 1024) if sys.platform == "darwin" else value / 1024, 1)


def audio_at_duration(source: np.ndarray, sample_rate: int, seconds: float) -> np.ndarray:
    samples = max(1, int(seconds * sample_rate))
    repeats = int(np.ceil(samples / max(1, len(source))))
    return np.tile(source, repeats)[:samples].astype(np.float32, copy=False)


def measure_profile(
    transcriber, cleaner, audio, sample_rate: int, runs: int,
    *, insertion_adapter: InsertionAdapter | None = None,
    protected_terms: Iterable[str] = (),
) -> dict:
    stage = {"stt": [], "cleanup": [], "total": []}
    if insertion_adapter is not None:
        stage.update({"direct_insertion": [], "direct_stop_to_insert": []})
    for _ in range(runs):
        started = time.perf_counter()
        target = insertion_adapter.capture_target() if insertion_adapter else None
        transcript = transcriber.transcribe(audio, sample_rate)
        stt_finished = time.perf_counter()
        if not transcript: raise RuntimeError("benchmark STT returned no text")
        candidate = cleaner.clean(transcript)
        cleaned = guarded_cleanup(
            transcript, candidate, protected_terms=protected_terms
        )
        cleanup_finished = time.perf_counter()
        if not cleaned: raise RuntimeError("benchmark cleanup returned no text")
        stage["stt"].append((stt_finished - started) * 1000)
        stage["cleanup"].append((cleanup_finished - stt_finished) * 1000)
        stage["total"].append((cleanup_finished - started) * 1000)
        if insertion_adapter is not None:
            ok, reason = insertion_adapter.insert(cleaned, target)
            inserted = time.perf_counter()
            if not ok:
                raise RuntimeError(f"benchmark insertion failed: {reason}")
            stage["direct_insertion"].append(
                (inserted - cleanup_finished) * 1000
            )
            stage["direct_stop_to_insert"].append((inserted - started) * 1000)
    return {key: summarize(values) for key, values in stage.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Content-free local batch benchmark")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--durations", default="2,10,60", help="comma-separated seconds")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--live-insertion", action="store_true",
        help=(
            "measure the direct component path through a real focus-checked "
            "paste; excludes Qt Controller dispatch"
        ),
    )
    args = parser.parse_args()
    if args.runs < 1: parser.error("--runs must be positive")
    durations = [float(item) for item in args.durations.split(",")]
    if not durations or any(item <= 0 for item in durations): parser.error("durations must be positive")
    if not ensure_sample(): return 1

    cfg = load_config(); source, sample_rate = load_wav_16k_mono(SAMPLE)
    stt_config = resolved_stt_config(cfg)
    cleanup_config = managed_cleanup_config(cfg.cleanup)
    transcriber = Transcriber(stt_config); cleaner = Cleaner(cleanup_config)
    insertion_adapter = LiveInsertionAdapter(cfg.insert) if args.live_insertion else None
    service_manager = None
    try:
        if cleanup_config.get("provider") in {"openai-compatible", "omlx"}:
            service_manager = LocalServiceManager(
                cleanup_config, secret_store=_EphemeralSecretStore()
            )
            cleaner.set_api_key(connect_owned_cleanup_service(service_manager))

        rss_before = peak_rss_mb()
        cold_started = time.perf_counter()
        transcriber.load()
        cleaner.warmup()
        warmup_ms = (time.perf_counter() - cold_started) * 1000
        profiles = {}
        names = ("short", "medium", "long")
        for index, seconds in enumerate(durations):
            audio = audio_at_duration(source, sample_rate, seconds)
            name = names[index] if index < len(names) else f"profile-{index+1}"
            profiles[name] = {
                "audio_seconds": seconds,
                **measure_profile(
                    transcriber, cleaner, audio, sample_rate, args.runs,
                    insertion_adapter=insertion_adapter,
                    protected_terms=cfg.personalization.get("vocabulary", ()),
                ),
            }
        result = {
            "schema": 4, "backend": "batch", "streaming_promoted": False,
            "measurement_scope": (
                "direct-components-with-insertion"
                if insertion_adapter is not None else "model-stages"
            ),
            "direct_stop_to_insert_measured": insertion_adapter is not None,
            "machine": platform.machine(), "macos": platform.mac_ver()[0],
            "python": platform.python_version(), "runs_per_profile": args.runs,
            "cold_warmup_ms": round(warmup_ms, 1),
            "peak_rss_mb": peak_rss_mb(),
            "rss_growth_mb": round(max(0, peak_rss_mb() - rss_before), 1),
            "stt_model": stt_config["model"],
            "stt_quant": stt_config.get("quant"),
            "stt_batch_size": stt_config["batch_size"],
            "performance_profile": cfg.performance.get("profile", "instant"),
            "cleanup_provider": cleanup_config.get("provider"),
            "cleanup_model": cleanup_config.get("model"),
            "profiles": profiles,
        }
        rendered = json.dumps(result, indent=2, sort_keys=True); print(rendered)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n")
        return 0
    finally:
        if service_manager is not None:
            service_manager.stop()


if __name__ == "__main__": raise SystemExit(main())
