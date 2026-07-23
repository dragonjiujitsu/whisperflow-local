"""Microphone capture via sounddevice.

The PortAudio callback stays light: it writes frames into a preallocated buffer
and pushes a single scalar RMS value to a queue for the overlay. No per-callback
allocation, no blocking. On buffer overflow (max_seconds reached) it stops the
stream so a forgotten session can't record forever.
"""
from __future__ import annotations

import math
import queue
import threading
from typing import Callable

import numpy as np
import sounddevice as sd


def input_device_names(query_devices=sd.query_devices) -> list[str]:
    """Return stable, human-readable input device names for Settings."""
    names = []
    for device in query_devices():
        name = str(device.get("name") or "").strip()
        if int(device.get("max_input_channels") or 0) > 0 and name not in names:
            names.append(name)
    return names


class Recorder:
    def __init__(
        self,
        cfg: dict,
        rms_queue: "queue.Queue[float]",
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        self._sr = int(cfg["sample_rate"])
        self._channels = int(cfg["channels"])
        self._device = str(cfg.get("input_device") or "").strip() or None
        self._max_samples = int(cfg["max_seconds"]) * self._sr
        self._max_seconds = int(cfg["max_seconds"])
        self._rms_q = rms_queue
        self._on_overflow = on_overflow

        self._buf = np.zeros(self._max_samples, dtype=np.float32)
        self._write = 0
        self.overflowed = False
        self._stream: sd.InputStream | None = None
        self._deadline: threading.Timer | None = None
        self._stream_lock = threading.Lock()

    @property
    def device_label(self) -> str:
        if self._device:
            return self._device
        try:
            return str(sd.query_devices(kind="input")["name"])
        except Exception:
            return "System default"

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
        self._cancel_deadline()
        self._write = 0
        self.overflowed = False
        self._stream = sd.InputStream(
            samplerate=self._sr,
            channels=self._channels,
            dtype="float32",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        self._deadline = threading.Timer(
            self._max_seconds, self._deadline_reached
        )
        self._deadline.daemon = True
        self._deadline.start()

    def stop(self) -> np.ndarray:
        self._cancel_deadline()
        with self._stream_lock:
            stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        return self._buf[:self._write].copy()

    def _cancel_deadline(self) -> None:
        deadline, self._deadline = self._deadline, None
        if deadline is not None:
            deadline.cancel()

    def _deadline_reached(self) -> None:
        """Release the microphone even if audio callbacks stop arriving."""
        with self._stream_lock:
            stream, self._stream = self._stream, None
        if stream is None:
            return
        self.overflowed = True
        try:
            stream.abort()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        if self._on_overflow is not None:
            try:
                self._on_overflow()
            except Exception:
                pass

    def rms_of(self, audio: np.ndarray) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio ** 2)))
