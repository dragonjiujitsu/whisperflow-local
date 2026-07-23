from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from whisperflow_local.__main__ import SAMPLE, ensure_sample, load_wav_16k_mono
from whisperflow_local.cleanup import Cleaner
from whisperflow_local.config import load_config
from whisperflow_local.stt import Transcriber


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


def measure_profile(transcriber, cleaner, audio, sample_rate: int, runs: int) -> dict:
    stage = {"stt": [], "cleanup": [], "total": []}
    for _ in range(runs):
        started = time.perf_counter(); transcript = transcriber.transcribe(audio, sample_rate)
        stt_finished = time.perf_counter()
        if not transcript: raise RuntimeError("benchmark STT returned no text")
        cleaned = cleaner.clean(transcript); finished = time.perf_counter()
        if not cleaned: raise RuntimeError("benchmark cleanup returned no text")
        stage["stt"].append((stt_finished - started) * 1000)
        stage["cleanup"].append((finished - stt_finished) * 1000)
        stage["total"].append((finished - started) * 1000)
    return {key: summarize(values) for key, values in stage.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Content-free local batch benchmark")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--durations", default="2,10,60", help="comma-separated seconds")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1: parser.error("--runs must be positive")
    durations = [float(item) for item in args.durations.split(",")]
    if not durations or any(item <= 0 for item in durations): parser.error("durations must be positive")
    if not ensure_sample(): return 1

    cfg = load_config(); source, sample_rate = load_wav_16k_mono(SAMPLE)
    transcriber = Transcriber(cfg.stt); cleaner = Cleaner(cfg.cleanup)
    rss_before = peak_rss_mb(); cold_started = time.perf_counter(); transcriber.load()
    try: cleaner.warmup()
    except Exception: pass
    warmup_ms = (time.perf_counter() - cold_started) * 1000
    profiles = {}
    names = ("short", "medium", "long")
    for index, seconds in enumerate(durations):
        audio = audio_at_duration(source, sample_rate, seconds)
        profiles[names[index] if index < len(names) else f"profile-{index+1}"] = {
            "audio_seconds": seconds,
            **measure_profile(transcriber, cleaner, audio, sample_rate, args.runs),
        }
    result = {
        "schema": 2, "backend": "batch", "streaming_promoted": False,
        "machine": platform.machine(), "macos": platform.mac_ver()[0],
        "python": platform.python_version(), "runs_per_profile": args.runs,
        "cold_warmup_ms": round(warmup_ms, 1), "peak_rss_mb": peak_rss_mb(),
        "rss_growth_mb": round(max(0, peak_rss_mb() - rss_before), 1),
        "stt_model": cfg.stt["model"], "stt_quant": cfg.stt.get("quant"),
        "cleanup_provider": cfg.cleanup.get("provider"), "cleanup_model": cfg.cleanup.get("model"),
        "profiles": profiles,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True); print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__": raise SystemExit(main())
