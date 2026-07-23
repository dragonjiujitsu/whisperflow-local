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
import resource
import sys
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .applog import get_logger
from .audio import Recorder
from .cleanup import Cleaner
from .config import Config
from .inserter import Inserter, capture_focus_target
from .metrics import MetricsCollector, PipelineMetric
from .overlay import VoicePill
from .evaluation import guarded_cleanup
from .history import HistoryStore
from .paths import AppPaths
from .profiles import resolve_writing_mode
from .recovery import RecoveryStore
from .session import SessionEvent, SessionPhase, SessionReducer
from .stt import Transcriber, audio_rejection_reason
from .vocabulary import VocabularyData, VocabularyStore

IDLE, RECORDING, PROCESSING = "IDLE", "RECORDING", "PROCESSING"

# sized for up to a ~5 min dictation (batch STT + LLM cleanup both run at stop)
STT_TIMEOUT_S = 90.0
CLEANUP_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    reason: str = ""
    recovered_to_clipboard: bool = False


def start_audio_session(recorder, play_start_cue) -> None:
    """Finish the PortAudio output cue before opening microphone input."""
    play_start_cue()
    recorder.start()


def stop_audio_session(recorder, play_stop_cue):
    """Close microphone input before opening the PortAudio output cue."""
    audio = recorder.stop()
    play_stop_cue()
    return audio


class Controller(QObject):
    # cross-thread signals (hotkey/worker -> Qt main thread)
    toggle_requested = Signal()
    cancel_requested = Signal()
    overflow_signal = Signal()  # audio callback -> main: hit max_seconds, finalize
    show_overlay = Signal()
    hide_overlay = Signal()
    fail_signal = Signal(str)  # worker -> main: nothing inserted (empty/abort/error)
    phase_signal = Signal(int, object)
    process_complete = Signal(int, object)
    health_signal = Signal(str, str)
    interrupt_signal = Signal(str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.log = get_logger(cfg.logging.get("metadata_only", True))
        self.sessions = SessionReducer()
        self.metrics = MetricsCollector(self.log)
        personal = cfg.personalization
        replacements = tuple(
            (str(pair[0]), str(pair[1]))
            for pair in personal.get("replacements", [])
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        )
        configured_vocabulary = VocabularyData(
            tuple(str(term) for term in personal.get("vocabulary", [])), replacements
        )
        try:
            stored_vocabulary = VocabularyStore(
                AppPaths.discover().support / "vocabulary.json"
            ).load()
            self.vocabulary = stored_vocabulary if (
                stored_vocabulary.terms or stored_vocabulary.replacements
            ) else configured_vocabulary
        except (OSError, ValueError):
            self.vocabulary = configured_vocabulary
        self.recovery = RecoveryStore(int(cfg.privacy.get("recovery_ttl_seconds", 900)))
        self._writing_mode = str(personal.get("writing_mode", "natural"))
        self._per_app_modes = dict(personal.get("per_app_modes", {}))
        history = cfg.history
        self.history = HistoryStore(
            AppPaths.discover().support / "history.json",
            enabled=bool(history.get("enabled", False)),
            retention_days=int(history.get("retention_days", 7)),
        )
        self._warmup_complete = False

        self.rms_q: "queue.Queue[float]" = queue.Queue(maxsize=64)
        # on max_seconds overflow the (PortAudio-thread) callback emits a queued
        # Qt signal so the finalize happens on the main thread, like a real stop
        self.recorder = Recorder(
            cfg.audio, self.rms_q, on_overflow=self.overflow_signal.emit
        )
        self.stt = Transcriber(cfg.stt)
        self.cleaner = Cleaner(cfg.cleanup)
        self.inserter = Inserter(cfg.insert)
        # Timed-out native/model work cannot be force-killed safely. Serializing
        # each backend prevents a newer session from running the same model
        # concurrently while the obsolete call winds down.
        self._stt_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()

        self.pill = VoicePill()
        self.pill.set_device_name(self.recorder.device_label)
        self._sr = int(cfg.audio["sample_rate"])
        self._sound = cfg.sound

        # overlay level pump (main-thread timer)
        self._pump = QTimer(self)
        self._pump.setInterval(33)
        self._pump.timeout.connect(self._drain_rms)

        self.toggle_requested.connect(self._on_toggle)
        self.cancel_requested.connect(self._on_cancel)
        self.overflow_signal.connect(self._on_overflow)
        self.show_overlay.connect(self._show)
        self.hide_overlay.connect(self._hide)
        self.fail_signal.connect(self._on_fail)
        self.phase_signal.connect(self._on_worker_phase)
        self.process_complete.connect(self._on_process_complete)
        self.interrupt_signal.connect(self._on_interrupt)

    @property
    def state(self) -> str:
        phase = self.sessions.current.phase
        if phase in {SessionPhase.IDLE, SessionPhase.READY,
                     SessionPhase.CANCELLED, SessionPhase.ERROR}:
            return IDLE
        if phase in {SessionPhase.STARTING, SessionPhase.RECORDING}:
            return RECORDING
        return PROCESSING

    # -- called from the pynput thread ---------------------------------------
    def on_hotkey(self) -> None:
        self.toggle_requested.emit()

    def on_system_event(self, event: str) -> None:
        self.interrupt_signal.emit(event)

    # -- main-thread slots ----------------------------------------------------
    def _on_toggle(self) -> None:
        if self.state == IDLE:
            self._start_recording()
        elif self.state == RECORDING:
            self._stop_and_process()
        # PROCESSING: ignored (no reentrancy)

    def _on_overflow(self) -> None:
        """Hit max_seconds: finalize exactly like a manual stop (transcribe what
        was said and insert it) instead of dropping the session silently."""
        if self.state != RECORDING:
            return
        self.log.info("max_seconds reached -> auto-finalize")
        print("[overflow] max recording length reached — finalizing", flush=True)
        self._stop_and_process()

    def _on_cancel(self) -> None:
        """Esc during RECORDING: discard audio, no STT/cleanup/paste."""
        if self.state != RECORDING:
            return
        session = self.sessions.current
        self.sessions.transition(session.session_id, SessionEvent.CANCELLED)
        self._pump.stop()
        self.hide_overlay.emit()
        self.recorder.stop()  # drop the buffer; nothing is processed
        self._beep_cancel()
        self.log.info("state=IDLE (cancelled)")

    def _on_interrupt(self, event: str) -> None:
        """Fail closed on sleep, device loss, or other native interruptions."""
        session = self.sessions.current
        if self.state == RECORDING:
            self._pump.stop()
            self.hide_overlay.emit()
            self.recorder.stop()
        if self.state != IDLE:
            try:
                self.sessions.transition(session.session_id, SessionEvent.CANCELLED)
            except ValueError:
                self.sessions.fail(session.session_id, f"interrupted:{event}")
        self.health_signal.emit("degraded", f"interrupted: {event}")
        self.log.info("session interrupted event=%s", event)

    def _start_recording(self) -> None:
        session = self.sessions.start()
        try:
            start_audio_session(
                self.recorder,
                lambda: self._beep(self._sound.get("start_freq", 920)),
            )
        except Exception as exc:
            self.sessions.fail(session.session_id, "microphone_unavailable")
            self.fail_signal.emit(f"microphone unavailable: {type(exc).__name__}")
            return
        self.sessions.transition(session.session_id, SessionEvent.RECORDING_STARTED)
        self.show_overlay.emit()
        self._pump.start()
        self.log.info("state=RECORDING")

    def _stop_and_process(self) -> None:
        session = self.sessions.current
        self.sessions.transition(session.session_id, SessionEvent.RECORDING_STOPPED)
        self._pump.stop()
        self.hide_overlay.emit()
        audio = stop_audio_session(
            self.recorder,
            lambda: self._beep(self._sound.get("stop_freq", 560)),
        )
        target = capture_focus_target()  # snapshot focus at STOP
        self.log.info(
            "state=PROCESSING audio_s=%.2f rms=%.6f device=%s overflow=%s",
            audio.size / self._sr, self.recorder.rms_of(audio),
            self.recorder.device_label, self.recorder.overflowed,
        )
        threading.Thread(
            target=self._process,
            args=(session.session_id, session.cancelled, audio, target),
            daemon=True,
        ).start()

    def _process(self, session_id, cancelled, audio, target) -> None:
        t0 = time.perf_counter()
        was_warm = self._warmup_complete
        try:
            self.phase_signal.emit(session_id, SessionEvent.TRANSCRIPTION_STARTED)
            completed, transcript = _with_timeout(
                lambda: _locked_call(
                    self._stt_lock, self.stt.transcribe, audio, self._sr
                ),
                STT_TIMEOUT_S,
                "",
            )
            t_stt = time.perf_counter()
            if not completed:
                cancelled.set()
                self._record_metric(
                    session_id, audio, t0, t_stt, t_stt, t_stt,
                    "stt_timeout", was_warm,
                )
                self.process_complete.emit(
                    session_id, ProcessResult(False, "transcription timed out")
                )
                return
            if cancelled.is_set():
                return
            if not transcript:
                rejection = audio_rejection_reason(audio, self._sr, self.cfg.stt)
                reason = {
                    "too_short": "recording too short",
                    "no_input_signal": f"no microphone signal from {self.recorder.device_label}",
                }.get(rejection, "no speech detected")
                self.log.info("stt=empty reason=%s -> no insert", rejection or "model")
                print(f"[timing] stt={ (t_stt-t0)*1000:.0f}ms -> empty, no insert",
                      flush=True)
                self.process_complete.emit(
                    session_id, ProcessResult(False, reason)
                )
                self._record_metric(
                    session_id, audio, t0, t_stt, t_stt, t_stt,
                    "no_speech", was_warm,
                )
                return
            transcript = self.vocabulary.apply(transcript)
            self.phase_signal.emit(session_id, SessionEvent.TRANSCRIPTION_FINISHED)
            mode = resolve_writing_mode(
                self._writing_mode, getattr(target, "bundle_id", ""), self._per_app_modes
            )
            vocabulary_instruction = ""
            if self.vocabulary.terms:
                vocabulary_instruction = " Preferred spellings: " + ", ".join(self.vocabulary.terms) + "."
            completed, cleaned = _with_timeout(
                lambda: _locked_call(
                    self._cleanup_lock, self.cleaner.clean, transcript, cancelled,
                    mode.instruction + vocabulary_instruction,
                ),
                CLEANUP_TIMEOUT_S,
                transcript,
            )
            t_clean = time.perf_counter()
            if not completed:
                cancelled.set()
                stashed = self._stash_to_clipboard(transcript)
                self._record_metric(
                    session_id, audio, t0, t_stt, t_clean, t_clean,
                    "cleanup_timeout", was_warm,
                )
                self.process_complete.emit(
                    session_id, ProcessResult(False, "cleanup timed out", stashed)
                )
                return
            if cancelled.is_set():
                return
            cleaned = guarded_cleanup(transcript, cleaned)
            self.history.add(cleaned)
            self.phase_signal.emit(session_id, SessionEvent.CLEANUP_FINISHED)
            ok, reason = self.inserter.insert(cleaned, target)
            t_ins = time.perf_counter()
            if not ok:
                # don't lose the words: leave the cleaned text on the clipboard
                # so the user can paste it manually (esp. on focus_changed)
                stashed = self._stash_to_clipboard(cleaned)
                detail = reason or "insert failed"
                self.process_complete.emit(
                    session_id, ProcessResult(False, detail, stashed)
                )
            else:
                self.process_complete.emit(session_id, ProcessResult(True))
            self._record_metric(
                session_id, audio, t0, t_stt, t_clean, t_ins,
                "inserted" if ok else (reason or "insert_failed"), was_warm,
            )
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
            self.process_complete.emit(
                session_id, ProcessResult(False, f"error: {type(exc).__name__}")
            )

    def _record_metric(
        self, session_id, audio, t0, t_stt, t_clean, t_ins,
        outcome: str, was_warm: bool,
    ) -> None:
        self.metrics.observe(PipelineMetric(
            session_id=session_id,
            audio_seconds=audio.size / self._sr,
            stt_ms=(t_stt - t0) * 1000,
            cleanup_ms=(t_clean - t_stt) * 1000,
            insert_ms=(t_ins - t_clean) * 1000,
            total_ms=(t_ins - t0) * 1000,
            outcome=outcome,
            stt_warm=was_warm,
            cleanup_warm=was_warm,
            peak_memory_mb=_peak_memory_mb(),
            backend_health="ready" if was_warm else "warming",
        ))

    def _on_worker_phase(self, session_id: int, event: object) -> None:
        if not self.sessions.is_active(session_id):
            return
        try:
            self.sessions.transition(session_id, event)
        except ValueError as exc:
            self.log.warning("ignored worker phase: %s", exc)

    def _on_process_complete(self, session_id: int, result: object) -> None:
        if session_id != self.sessions.current.session_id:
            self.log.info("ignored stale result session=%s", session_id)
            return
        if not isinstance(result, ProcessResult):
            self.sessions.fail(session_id, "invalid_worker_result")
            self._on_fail("invalid worker result")
            return
        if result.ok:
            try:
                self.sessions.transition(session_id, SessionEvent.INSERTION_FINISHED)
            except ValueError as exc:
                self.sessions.fail(session_id, "invalid_completion_order")
                self._on_fail(str(exc))
                return
            self.log.info("state=READY")
            return
        self.sessions.fail(session_id, result.reason)
        detail = result.reason
        if result.recovered_to_clipboard:
            detail += " — text on clipboard"
        self._on_fail(detail)

    def _stash_to_clipboard(self, text: str) -> bool:
        """Best-effort: put uninserted text on the clipboard for manual paste."""
        self.recovery.add(text, "automatic insertion unavailable")
        try:
            from . import clipboard

            clipboard.copy(text)
            return True
        except Exception as exc:
            self.log.warning("clipboard stash failed: %s", exc)
            return False

    # -- main-thread slot: surface a silent failure to the user ---------------
    def _on_fail(self, reason: str) -> None:
        self.log.info("fail reason=%s", reason)
        print(f"[fail] {reason} — nothing inserted", flush=True)
        self.pill.flash_error()
        self._beep_error()

    def _drain_rms(self) -> None:
        level = 0.0
        try:
            while True:
                level = self.rms_q.get_nowait()
        except queue.Empty:
            pass
        # perceptual scaling: a power curve lifts quiet/normal speech so the
        # waves react well below shouting volume (linear felt dead at low input)
        self.pill.set_level(level)

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

    def _beep_error(self) -> None:
        if not self._sound.get("enabled", False):
            return
        from . import sound

        sound.play_error(
            float(self._sound.get("error_freq", 196)),
            float(self._sound.get("volume", 0.06)),
        )

    def _beep_cancel(self) -> None:
        if not self._sound.get("enabled", False):
            return
        from . import sound

        sound.play_tone(
            float(self._sound.get("cancel_freq", 311)),
            int(self._sound.get("duration_ms", 110)),
            float(self._sound.get("volume", 0.06)),
        )

    def warmup(self) -> None:
        with self._stt_lock:
            self.stt.load()
        try:
            with self._cleanup_lock:
                self.cleaner.warmup()
        except Exception as exc:
            self.log.warning("cleanup warmup failed: %s", exc)
        finally:
            self._warmup_complete = True


def _with_timeout(fn, timeout_s: float, fallback):
    """Run fn on a thread and report whether it completed before its deadline."""
    result = {"value": fallback}

    def runner():
        result["value"] = fn()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return False, fallback
    return True, result["value"]


def _locked_call(lock, fn, *args):
    with lock:
        return fn(*args)


def _peak_memory_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024
