"""Speech-to-text via faster-whisper, with confidence gating.

Rejects empty/hallucinated output (Whisper emits phantom text on silence) using
the thresholds in config: min duration, RMS floor, no_speech_prob, avg logprob.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np


def _register_cuda_dlls() -> None:
    """ctranslate2 doesn't auto-load the pip NVIDIA CUDA DLLs on Windows.
    Add the nvidia/*/bin dirs (cuBLAS, cuDNN) to the DLL search path so
    cublas64_12.dll / cudnn*.dll resolve."""
    if sys.platform != "win32":
        return
    import site as _site
    import sysconfig

    roots: set[str] = set(sys.path)
    for key in ("purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            roots.add(p)
    try:
        roots.update(_site.getsitepackages())
    except Exception:
        pass

    roots.add(str(Path(sys.prefix) / "Lib" / "site-packages"))

    bin_dirs: list[str] = []
    for root in roots:
        nvidia = Path(root) / "nvidia"
        if not nvidia.is_dir():
            continue
        for binp in nvidia.glob("*/bin"):
            bin_dirs.append(str(binp))

    for binp in dict.fromkeys(bin_dirs):  # dedup, keep order
        try:
            os.add_dll_directory(binp)
        except (OSError, FileNotFoundError):
            pass
    # ctranslate2's own loader searches PATH (not add_dll_directory dirs),
    # so prepend the CUDA bin dirs to PATH as well — this is what actually
    # resolves cublas64_12.dll / cudnn*.dll at encode time.
    if bin_dirs:
        os.environ["PATH"] = os.pathsep.join(bin_dirs) + os.pathsep + os.environ.get("PATH", "")


class Transcriber:
    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._model = None  # lazy: importing faster_whisper loads CUDA libs
        self._pipe = None   # batched pipeline (or the model itself)

    def load(self) -> None:
        _register_cuda_dlls()
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self._model = WhisperModel(
            self._cfg["model"],
            device=self._cfg.get("device", "cuda"),
            compute_type=self._cfg.get("compute_type", "float16"),
        )
        if self._cfg.get("batched", True):
            self._pipe = BatchedInferencePipeline(model=self._model)
        else:
            self._pipe = self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if self._model is None:
            self.load()

        duration = audio.size / sample_rate
        rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
        if duration < float(self._cfg["min_duration_s"]):
            return ""
        if rms < float(self._cfg["min_rms"]):
            return ""

        beam = int(self._cfg.get("beam_size", 1))
        if self._cfg.get("batched", True):
            segments, _info = self._pipe.transcribe(
                audio,
                language="en",
                beam_size=beam,
                batch_size=int(self._cfg.get("batch_size", 16)),
                condition_on_previous_text=False,
            )
        else:
            segments, _info = self._model.transcribe(
                audio,
                language="en",
                vad_filter=True,
                beam_size=beam,
                condition_on_previous_text=False,
            )

        parts: list[str] = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0.0) > float(self._cfg["max_no_speech_prob"]):
                continue
            if getattr(seg, "avg_logprob", 0.0) < float(self._cfg["min_avg_logprob"]):
                continue
            parts.append(seg.text)

        return " ".join(p.strip() for p in parts).strip()
