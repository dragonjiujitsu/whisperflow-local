"""Microphone capture via sounddevice.

The PortAudio callback stays light: it writes frames into a preallocated buffer
and pushes a single scalar RMS value to a queue for the overlay. No per-callback
allocation, no blocking. On buffer overflow (max_seconds reached) it stops the
stream so a forgotten session can't record forever.
"""
from __future__ import annotations

import math
import queue
from typing import Callable

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(
        self,
        cfg: dict,
        rms_queue: "queue.Queue[float]",
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        self._sr = int(cfg["sample_rate"])
        self._channels = int(cfg["channels"])
        self._max_samples = int(cfg["max_seconds"]) * self._sr
        self._rms_q = rms_queue
        self._on_overflow = on_overflow

        self._buf = np.zeros(self._max_samples, dtype=np.float32)
        self._write = 0
        self.overflowed = False
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        # scalar RMS for the overlay (cheap)
        rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
        if math.isnan(rms):
            rms = 0.0
        try:
            self._rms_q.put_nowait(rms)
        except queue.Full:
            pass

        end = self._write + frames
        if end > self._max_samples:
            frames = self._max_samples - self._write
            end = self._max_samples
            self.overflowed = True
        if frames > 0:
            self._buf[self._write:end] = indata[:frames, 0]
            self._write = end
        if self.overflowed:
            # notify the controller to finalize on the main thread, then stop
            if self._on_overflow is not None:
                try:
                    self._on_overflow()
                except Exception:
                    pass
            raise sd.CallbackStop()

    def start(self) -> None:
        self._write = 0
        self.overflowed = False
        self._stream = sd.InputStream(
            samplerate=self._sr,
            channels=self._channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return self._buf[:self._write].copy()

    def rms_of(self, audio: np.ndarray) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio ** 2)))
