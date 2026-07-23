"""App-owned local speech-to-text through MLX on Apple Silicon."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np

from .paths import AppPaths

MODEL_REPOS = {
    "tiny": {"base": "mlx-community/whisper-tiny", "4bit": "mlx-community/whisper-tiny-mlx-4bit", "8bit": "mlx-community/whisper-tiny-mlx-8bit"},
    "small": {"base": "mlx-community/whisper-small-mlx", "4bit": "mlx-community/whisper-small-mlx-4bit", "8bit": "mlx-community/whisper-small-mlx-8bit"},
    "base": {"base": "mlx-community/whisper-base-mlx", "4bit": "mlx-community/whisper-base-mlx-4bit", "8bit": "mlx-community/whisper-base-mlx-8bit"},
    "medium": {"base": "mlx-community/whisper-medium-mlx", "4bit": "mlx-community/whisper-medium-mlx-4bit", "8bit": "mlx-community/whisper-medium-mlx-8bit"},
    "large-v2": {"base": "mlx-community/whisper-large-v2-mlx", "4bit": "mlx-community/whisper-large-v2-mlx-4bit", "8bit": "mlx-community/whisper-large-v2-mlx-8bit"},
    "large-v3": {"base": "mlx-community/whisper-large-v3-mlx", "4bit": "mlx-community/whisper-large-v3-mlx-4bit", "8bit": "mlx-community/whisper-large-v3-mlx-8bit"},
    "distil-small.en": {"base": "mustafaaljadery/distil-whisper-mlx"},
    "distil-medium.en": {"base": "mustafaaljadery/distil-whisper-mlx"},
    "distil-large-v2": {"base": "mustafaaljadery/distil-whisper-mlx"},
    "distil-large-v3": {"base": "mustafaaljadery/distil-whisper-mlx"},
}


def audio_rejection_reason(audio: np.ndarray, sample_rate: int, cfg: dict) -> str:
    duration = audio.size / sample_rate
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    if duration < float(cfg["min_duration_s"]):
        return "too_short"
    if rms < float(cfg["min_rms"]):
        return "no_input_signal"
    return ""


class Transcriber:
    def __init__(self, cfg: dict, paths: AppPaths | None = None) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("whisperflow-local is configured for macOS Apple Silicon")
        self._cfg = cfg
        self._paths = paths or AppPaths.discover()
        self._model_path: Path | None = None
        self._transcribe_audio = None

    @property
    def model_path(self) -> Path:
        name = _model_name(self._cfg)
        return self._paths.models / "Speech" / name

    def load(self) -> None:
        from lightning_whisper_mlx.transcribe import transcribe_audio

        self._model_path = ensure_speech_model(self._cfg, self._paths)
        self._transcribe_audio = transcribe_audio

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if audio_rejection_reason(audio, sample_rate, self._cfg):
            return ""
        if self._model_path is None: self.load()
        return self._transcribe_mlx(audio, sample_rate)

    def _transcribe_mlx(self, audio: np.ndarray, sample_rate: int) -> str:
        if sample_rate != 16000: raise ValueError("lightning-whisper-mlx expects 16 kHz audio")
        result = self._transcribe_audio(
            audio.astype(np.float32, copy=False), path_or_hf_repo=str(self._model_path),
            language="en", batch_size=int(self._cfg.get("batch_size", 12)),
            condition_on_previous_text=False,
        )
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        return text.strip()


def ensure_speech_model(cfg: dict, paths: AppPaths) -> Path:
    destination = paths.models / "Speech" / _model_name(cfg)
    if _complete(destination): return destination
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    legacy = Path(__file__).resolve().parents[1] / "mlx_models" / _model_name(cfg)
    if _complete(legacy):
        for name in ("weights.npz", "config.json"):
            _link_or_copy(legacy / name, destination / name)
        return destination
    try:
        from huggingface_hub import hf_hub_download
        model = str(cfg["model"]); quant = str(cfg.get("quant") or "base")
        repo = MODEL_REPOS[model][quant]
        for name in ("weights.npz", "config.json"):
            remote = f"mlx_models/{_model_name(cfg)}/{name}" if model.startswith("distil") else name
            cached = Path(hf_hub_download(repo_id=repo, filename=remote))
            _link_or_copy(cached, destination / name)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def _model_name(cfg: dict) -> str:
    model = str(cfg["model"]); quant = cfg.get("quant")
    suffix = {"4bit": "4-bit", "8bit": "8-bit"}.get(str(quant), str(quant))
    return f"{model}-{suffix}" if quant and model.startswith("distil") else model


def _complete(path: Path) -> bool:
    return (path / "weights.npz").is_file() and (path / "config.json").is_file()


def _link_or_copy(source: Path, destination: Path) -> None:
    if destination.exists(): return
    try: os.link(source, destination)
    except OSError: shutil.copy2(source, destination)
