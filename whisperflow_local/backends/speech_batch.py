from __future__ import annotations

from threading import Event

import numpy as np

from ..stt import Transcriber


class BatchSpeechBackend:
    """Adapter that preserves the proven stop-and-transcribe implementation."""

    name = "lightning-whisper-mlx-batch"

    def __init__(self, config: dict) -> None:
        self.transcriber = Transcriber(config)

    def load(self) -> None:
        self.transcriber.load()

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, cancelled: Event | None = None
    ) -> str:
        if cancelled is not None and cancelled.is_set():
            return ""
        result = self.transcriber.transcribe(audio, sample_rate)
        return "" if cancelled is not None and cancelled.is_set() else result
