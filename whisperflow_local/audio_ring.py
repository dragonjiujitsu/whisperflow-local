"""Preallocated single-producer/single-consumer audio ring for callbacks."""
from __future__ import annotations

import threading

import numpy as np


class AudioChunkRing:
    def __init__(self, capacity: int, chunk_samples: int) -> None:
        if capacity < 1 or chunk_samples < 1:
            raise ValueError("capacity and chunk_samples must be positive")
        self._buffers = np.zeros((capacity, chunk_samples), dtype=np.float32)
        self._lengths = np.zeros(capacity, dtype=np.int32)
        self._sequences = np.zeros(capacity, dtype=np.int64)
        self._capacity = capacity
        self._chunk_samples = chunk_samples
        self._write = 0
        self._read = 0
        self._count = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def try_write(self, sequence: int, samples: np.ndarray) -> bool:
        """Bounded copy into preallocated storage; safe for the audio callback."""
        length = min(len(samples), self._chunk_samples)
        if not self._lock.acquire(blocking=False):
            self._dropped += 1
            return False
        try:
            if self._count == self._capacity:
                self._read = (self._read + 1) % self._capacity
                self._count -= 1
                self._dropped += 1
            np.copyto(self._buffers[self._write, :length], samples[:length], casting="unsafe")
            self._lengths[self._write] = length
            self._sequences[self._write] = sequence
            self._write = (self._write + 1) % self._capacity
            self._count += 1
            return True
        finally:
            self._lock.release()

    def read(self) -> tuple[int, np.ndarray] | None:
        with self._lock:
            if not self._count:
                return None
            slot = self._read
            length = int(self._lengths[slot])
            result = int(self._sequences[slot]), self._buffers[slot, :length].copy()
            self._read = (self._read + 1) % self._capacity
            self._count -= 1
            return result

    @property
    def dropped(self) -> int:
        return self._dropped
