"""Backend-neutral streaming mechanics; inference never runs in the audio callback."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .backends.base import PartialTranscript, StreamingSpeechBackend


@dataclass(frozen=True)
class StreamStats:
    submitted: int
    processed: int
    dropped: int
    peak_queue: int


class BoundedAudioQueue:
    """Nonblocking newest-audio queue with explicit pressure accounting."""

    def __init__(self, capacity: int = 4) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._queue: queue.Queue[tuple[int, np.ndarray]] = queue.Queue(capacity)
        self._submitted = 0
        self._processed = 0
        self._dropped = 0
        self._peak = 0
        self._lock = threading.Lock()

    def submit(self, sequence: int, audio: np.ndarray) -> bool:
        """Copy and enqueue without blocking; drop oldest work under pressure."""
        item = (sequence, np.asarray(audio, dtype=np.float32).copy())
        with self._lock:
            self._submitted += 1
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            with self._lock:
                self._dropped += 1
            self._queue.put_nowait(item)
        with self._lock:
            self._peak = max(self._peak, self._queue.qsize())
        return True

    def get(self, timeout: float = 0.1) -> tuple[int, np.ndarray]:
        return self._queue.get(timeout=timeout)

    def done(self) -> None:
        self._queue.task_done()
        with self._lock:
            self._processed += 1

    def stats(self) -> StreamStats:
        with self._lock:
            return StreamStats(self._submitted, self._processed, self._dropped, self._peak)


class StablePrefixReconciler:
    """Publishes only words confirmed by consecutive rolling-window hypotheses."""

    def __init__(self) -> None:
        self._previous: list[str] = []
        self._stable: list[str] = []

    @property
    def stable_text(self) -> str:
        return " ".join(self._stable)

    def update(self, hypothesis: str, audio_end_s: float, sequence: int) -> PartialTranscript:
        words = hypothesis.strip().split()
        common = 0
        for old, new in zip(self._previous, words):
            if old != new:
                break
            common += 1
        # Stability never moves backward. A revised unstable suffix remains editable.
        confirmed = max(len(self._stable), common)
        if words[: len(self._stable)] != self._stable:
            confirmed = len(self._stable)
            words = self._stable + words[len(self._stable) :]
        self._stable = words[:confirmed]
        self._previous = words
        return PartialTranscript(
            text=" ".join(words), stable_text=self.stable_text,
            audio_end_s=audio_end_s, sequence=sequence,
        )

    def finalize(self, authoritative_text: str, audio_end_s: float, sequence: int) -> PartialTranscript:
        text = authoritative_text.strip()
        self._previous = text.split()
        self._stable = list(self._previous)
        return PartialTranscript(text, text, audio_end_s, sequence, final=True)


class StreamingSession:
    """Consumes bounded windows on a worker and reconciles with a final batch result."""

    def __init__(
        self,
        backend: StreamingSpeechBackend,
        sample_rate: int,
        on_partial: Callable[[PartialTranscript], None],
        capacity: int = 4,
    ) -> None:
        self.backend = backend
        self.sample_rate = sample_rate
        self.on_partial = on_partial
        self.queue = BoundedAudioQueue(capacity)
        self.reconciler = StablePrefixReconciler()
        self.cancelled = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("stream already started")
        self._thread = threading.Thread(target=self._consume, daemon=True)
        self._thread.start()

    def submit(self, sequence: int, audio: np.ndarray) -> bool:
        return False if self.cancelled.is_set() else self.queue.submit(sequence, audio)

    def cancel(self) -> None:
        self.cancelled.set()

    def finalize(self, full_audio: np.ndarray, sequence: int) -> PartialTranscript | None:
        self.cancelled.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        # Final output is always authoritative batch inference, never a partial guess.
        final = self.backend.transcribe(full_audio, self.sample_rate)
        if not final:
            return None
        result = self.reconciler.finalize(final, len(full_audio) / self.sample_rate, sequence)
        self.on_partial(result)
        return result

    def _consume(self) -> None:
        while not self.cancelled.is_set():
            try:
                sequence, audio = self.queue.get()
            except queue.Empty:
                continue
            try:
                text = self.backend.transcribe_window(
                    audio, self.sample_rate, sequence, self.cancelled
                )
                if text and not self.cancelled.is_set():
                    self.on_partial(self.reconciler.update(
                        text, len(audio) / self.sample_rate, sequence
                    ))
            finally:
                self.queue.done()
