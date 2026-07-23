from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class PartialTranscript:
    text: str
    stable_text: str
    audio_end_s: float
    sequence: int
    final: bool = False


class SpeechBackend(Protocol):
    name: str

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, cancelled: Event | None = None
    ) -> str: ...


class StreamingSpeechBackend(SpeechBackend, Protocol):
    def transcribe_window(
        self,
        audio: np.ndarray,
        sample_rate: int,
        sequence: int,
        cancelled: Event | None = None,
    ) -> str: ...
