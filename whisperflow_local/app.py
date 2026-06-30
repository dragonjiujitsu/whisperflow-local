"""Orchestrator: hotkey -> record -> (worker) STT -> cleanup -> focus-safe insert,
with the overlay pill driven by live mic RMS.

Threading model (PLAN.md):
  - pynput hotkey callback runs on its own thread -> marshalled into Qt via a signal.
  - audio capture runs in the PortAudio callback thread.
  - STT + cleanup run on a worker thread so the UI never freezes.
  - ALL UI updates happen on the Qt main thread via queued signals/timers.
"""
from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .applog import get_logger
from .audio import Recorder
from .cleanup import Cleaner
from .config import Config
from .inserter import Inserter, capture_focus_target
from .overlay import VoicePill
from .stt import Transcriber

IDLE, RECORDING, PROCESSING = "IDLE", "RECORDING", "PROCESSING"

STT_TIMEOUT_S = 30.0
CLEANUP_TIMEOUT_S = 30.0


class Controller(QObject):
    # cross-thread signals (hotkey/worker -> Qt main thread)
    toggle_requested = Signal()
    show_overlay = Signal()
    hide_overlay = Signal()

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.log = get_logger(cfg.logging.get("metadata_only", True))
        self.state = IDLE

        self.rms_q: "queue.Queue[float]" = queue.Queue(maxsize=64)
        self.recorder = Recorder(cfg.audio, self.rms_q)
        self.stt = Transcriber(cfg.stt)
        self.cleaner = Cleaner(cfg.cleanup)
        self.inserter = Inserter(cfg.insert)

        self.pill = VoicePill()
        self._sr = int(cfg.audio["sample_rate"])

        # overlay level pump (main-thread timer)
        self._pump = QTimer(self)
        self._pump.setInterval(33)
        self._pump.timeout.connect(self._drain_rms)

        self.toggle_requested.connect(self._on_toggle)
        self.show_overlay.connect(self._show)
        self.hide_overlay.connect(self._hide)

    # -- called from the pynput thread ---------------------------------------
    def on_hotkey(self) -> None:
        self.toggle_requested.emit()

    # -- main-thread slots ----------------------------------------------------
    def _on_toggle(self) -> None:
        if self.state == IDLE:
            self._start_recording()
        elif self.state == RECORDING:
            self._stop_and_process()
        # PROCESSING: ignored (no reentrancy)

    def _start_recording(self) -> None:
        self.state = RECORDING
        self.recorder.start()
        self.show_overlay.emit()
        self._pump.start()
        self.log.info("state=RECORDING")

    def _stop_and_process(self) -> None:
        self.state = PROCESSING
        self._pump.stop()
        self.hide_overlay.emit()
        target = capture_focus_target()  # snapshot focus at STOP
        audio = self.recorder.stop()
        self.log.info("state=PROCESSING audio_s=%.2f overflow=%s",
                      audio.size / self._sr, self.recorder.overflowed)
        threading.Thread(target=self._process, args=(audio, target), daemon=True).start()

    def _process(self, audio, target) -> None:
        try:
            transcript = _with_timeout(
                lambda: self.stt.transcribe(audio, self._sr), STT_TIMEOUT_S, ""
            )
            if not transcript:
                self.log.info("stt=empty -> no insert")
                return
            cleaned = _with_timeout(
                lambda: self.cleaner.clean(transcript), CLEANUP_TIMEOUT_S, transcript
            )
            ok, reason = self.inserter.insert(cleaned, target)
            self.log.info("insert ok=%s reason=%s chars=%d", ok, reason, len(cleaned))
        except Exception as exc:  # guarantee return to IDLE
            self.log.exception("process error: %s", type(exc).__name__)
        finally:
            self.state = IDLE
            self.log.info("state=IDLE")

    def _drain_rms(self) -> None:
        level = 0.0
        try:
            while True:
                level = self.rms_q.get_nowait()
        except queue.Empty:
            pass
        # scale RMS (~0..0.2 typical speech) into 0..1
        self.pill.set_level(min(1.0, level * 6.0))

    def _show(self) -> None:
        if self.cfg.overlay.get("enabled", True):
            self.pill.show_pill()

    def _hide(self) -> None:
        self.pill.hide_pill()

    def warmup(self) -> None:
        self.stt.load()
        try:
            self.cleaner.warmup()
        except Exception as exc:
            self.log.warning("cleanup warmup failed: %s", exc)


def _with_timeout(fn, timeout_s: float, fallback):
    """Run fn on a thread; return its result or `fallback` if it overruns."""
    result = {"value": fallback}

    def runner():
        result["value"] = fn()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return fallback
    return result["value"]
