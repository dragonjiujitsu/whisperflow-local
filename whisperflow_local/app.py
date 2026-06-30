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

from pynput import keyboard
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
        self._enter_listener: keyboard.Listener | None = None
        self._sound = cfg.sound

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
        self._beep(self._sound.get("start_freq", 920))
        self.recorder.start()
        self.show_overlay.emit()
        self._pump.start()
        self._start_enter_stop()  # Enter also finishes (only while recording)
        self.log.info("state=RECORDING")

    def _stop_and_process(self) -> None:
        self.state = PROCESSING
        self._beep(self._sound.get("stop_freq", 560))
        self._stop_enter_stop()
        self._pump.stop()
        self.hide_overlay.emit()
        target = capture_focus_target()  # snapshot focus at STOP
        audio = self.recorder.stop()
        self.log.info("state=PROCESSING audio_s=%.2f overflow=%s",
                      audio.size / self._sr, self.recorder.overflowed)
        threading.Thread(target=self._process, args=(audio, target), daemon=True).start()

    def _process(self, audio, target) -> None:
        t0 = time.perf_counter()
        try:
            transcript = _with_timeout(
                lambda: self.stt.transcribe(audio, self._sr), STT_TIMEOUT_S, ""
            )
            t_stt = time.perf_counter()
            if not transcript:
                self.log.info("stt=empty -> no insert")
                print(f"[timing] stt={ (t_stt-t0)*1000:.0f}ms -> empty, no insert",
                      flush=True)
                return
            cleaned = _with_timeout(
                lambda: self.cleaner.clean(transcript), CLEANUP_TIMEOUT_S, transcript
            )
            t_clean = time.perf_counter()
            ok, reason = self.inserter.insert(cleaned, target)
            t_ins = time.perf_counter()
            audio_s = audio.size / self._sr
            print(
                f"[timing] audio={audio_s:.1f}s | stt={(t_stt-t0)*1000:.0f}ms "
                f"| cleanup={(t_clean-t_stt)*1000:.0f}ms "
                f"| insert={(t_ins-t_clean)*1000:.0f}ms "
                f"| total={(t_ins-t0)*1000:.0f}ms | ok={ok}",
                flush=True,
            )
            self.log.info(
                "timing audio_s=%.1f stt_ms=%.0f cleanup_ms=%.0f insert_ms=%.0f total_ms=%.0f ok=%s",
                audio_s, (t_stt-t0)*1000, (t_clean-t_stt)*1000,
                (t_ins-t_clean)*1000, (t_ins-t0)*1000, ok,
            )
        except Exception as exc:  # guarantee return to IDLE
            self.log.exception("process error: %s", type(exc).__name__)
        finally:
            self.state = IDLE
            self.log.info("state=IDLE")

    # -- Enter-to-finish (active only during RECORDING) -----------------------
    def _start_enter_stop(self) -> None:
        VK_RETURN = 0x0D

        def win32_filter(msg, data):
            if data.vkCode == VK_RETURN and self.state == RECORDING:
                # Trigger the stop FIRST: suppress_event() raises a sentinel to
                # swallow the keystroke (no stray newline), so anything after it
                # would be dead code.
                self.toggle_requested.emit()
                self._enter_listener.suppress_event()

        self._enter_listener = keyboard.Listener(
            on_press=lambda k: None, win32_event_filter=win32_filter
        )
        self._enter_listener.start()

    def _stop_enter_stop(self) -> None:
        if self._enter_listener is not None:
            self._enter_listener.stop()
            self._enter_listener = None

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

    def _beep(self, freq: int) -> None:
        if not self._sound.get("enabled", False):
            return
        from . import sound

        sound.play_tone(
            float(freq),
            int(self._sound.get("duration_ms", 110)),
            float(self._sound.get("volume", 0.06)),
        )

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
