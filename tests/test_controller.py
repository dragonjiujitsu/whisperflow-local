from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from whisperflow_local.app import (
    PROCESSING,
    Controller,
    ProcessResult,
    _resolved_stt_config,
    _with_timeout,
)
from whisperflow_local.session import SessionEvent, SessionPhase, SessionReducer


class TimeoutTests(unittest.TestCase):
    def test_completed_call_reports_value(self) -> None:
        completed, value = _with_timeout(lambda: "done", 0.2, "fallback")
        self.assertTrue(completed)
        self.assertEqual(value, "done")

    def test_timed_out_call_reports_fallback(self) -> None:
        release = threading.Event()
        completed, value = _with_timeout(
            lambda: release.wait(1.0), 0.01, "fallback"
        )
        release.set()
        self.assertFalse(completed)
        self.assertEqual(value, "fallback")

    def test_model_exception_is_not_converted_to_a_fallback(self) -> None:
        def fail() -> str:
            raise RuntimeError("model failed")

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            _with_timeout(fail, 0.2, "fallback")

    def test_busy_backend_rejects_without_spawning_or_queueing(self) -> None:
        lock = threading.Lock()
        release = threading.Event()
        calls = []

        def work(wait: bool) -> str:
            calls.append(wait)
            if wait:
                release.wait(0.5)
            return "ok"

        first_done, _ = _with_timeout(
            lambda: work(True), 0.01, "timeout", lock=lock
        )
        self.assertFalse(first_done)
        started = time.perf_counter()
        second_result = _with_timeout(
            lambda: work(False), 0.4, "timeout", lock=lock
        )
        self.assertLess(time.perf_counter() - started, 0.1)
        self.assertEqual(second_result, (False, "timeout"))
        self.assertEqual(calls, [True])
        release.set()

    def test_single_flight_releases_lock_after_exception(self) -> None:
        lock = threading.Lock()

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            _with_timeout(
                lambda: (_ for _ in ()).throw(RuntimeError("model failed")),
                0.2,
                "fallback",
                lock=lock,
            )

        self.assertEqual(
            _with_timeout(lambda: "recovered", 0.2, "fallback", lock=lock),
            (True, "recovered"),
        )


class CompletionContractTests(unittest.TestCase):
    def test_stale_completion_cannot_advance_new_session(self) -> None:
        reducer = SessionReducer()
        old = reducer.start()
        reducer.transition(old.session_id, SessionEvent.RECORDING_STARTED)
        new = reducer.start()
        result = ProcessResult(True)
        self.assertTrue(result.ok)
        reducer.transition(old.session_id, SessionEvent.INSERTION_FINISHED)
        self.assertEqual(reducer.current.session_id, new.session_id)
        self.assertEqual(reducer.current.phase, SessionPhase.STARTING)

    @staticmethod
    def _controller_at_inserting() -> tuple[SimpleNamespace, int]:
        sessions = SessionReducer()
        session = sessions.start()
        for event in (
            SessionEvent.RECORDING_STARTED,
            SessionEvent.RECORDING_STOPPED,
            SessionEvent.TRANSCRIPTION_STARTED,
            SessionEvent.TRANSCRIPTION_FINISHED,
            SessionEvent.CLEANUP_FINISHED,
        ):
            sessions.transition(session.session_id, event)
        fake = SimpleNamespace(
            sessions=sessions,
            history=Mock(),
            inserter=Mock(),
            log=Mock(),
            _stash_to_clipboard=Mock(return_value=True),
            _on_fail=Mock(),
            _record_completed_result=Mock(),
        )
        return fake, session.session_id

    def test_cancelled_completion_has_no_user_visible_side_effects(self) -> None:
        fake, session_id = self._controller_at_inserting()
        fake.sessions.transition(session_id, SessionEvent.CANCELLED)

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(True, text="cleaned", target=object()),
        )

        fake.history.add.assert_not_called()
        fake.inserter.insert.assert_not_called()
        fake._stash_to_clipboard.assert_not_called()

    def test_active_completion_authorizes_history_and_insert_on_main_thread(self) -> None:
        fake, session_id = self._controller_at_inserting()
        target = object()
        fake.inserter.insert.return_value = (True, "")

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(True, text="cleaned", target=target),
        )

        fake.history.add.assert_called_once_with("cleaned")
        fake.inserter.insert.assert_called_once_with("cleaned", target)
        self.assertEqual(fake.sessions.current.phase, SessionPhase.READY)

    def test_optional_history_failure_does_not_block_insertion(self) -> None:
        fake, session_id = self._controller_at_inserting()
        fake.history.add.side_effect = OSError("disk unavailable")
        fake.inserter.insert.return_value = (True, "")

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(True, text="cleaned", target=object()),
        )

        fake.inserter.insert.assert_called_once()
        self.assertEqual(fake.sessions.current.phase, SessionPhase.READY)

    def test_history_write_occurs_after_insert_timing_is_captured(self) -> None:
        fake, session_id = self._controller_at_inserting()
        events = []
        fake.inserter.insert.side_effect = lambda *_: (events.append("insert") or (True, ""))
        fake._record_completed_result.side_effect = lambda *_: events.append("timing")
        fake.history.add.side_effect = lambda *_: events.append("history")

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(True, text="cleaned", target=object()),
        )

        self.assertEqual(events, ["insert", "timing", "history"])

    def test_confirmation_failures_record_recovery_without_rewriting_clipboard(
        self,
    ) -> None:
        for reason in (
            "focus_changed",
            "focus_changed_during_paste",
            "paste_unconfirmed",
        ):
            with self.subTest(reason=reason):
                fake, session_id = self._controller_at_inserting()
                fake.inserter.insert.return_value = (False, reason)

                Controller._on_process_complete(
                    fake,
                    session_id,
                    ProcessResult(True, text="cleaned", target=object()),
                )

                fake._stash_to_clipboard.assert_called_once_with(
                    "cleaned", write_clipboard=False
                )

    def test_unexpected_insert_exception_recovers_active_text(self) -> None:
        fake, session_id = self._controller_at_inserting()
        fake.inserter.insert.side_effect = RuntimeError("native failure")

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(True, text="cleaned", target=object()),
        )

        fake._stash_to_clipboard.assert_called_once_with("cleaned")
        fake._on_fail.assert_called_once()
        self.assertEqual(fake.sessions.current.phase, SessionPhase.ERROR)

    def test_recovery_is_only_written_for_an_active_session(self) -> None:
        fake, session_id = self._controller_at_inserting()
        fake.sessions.transition(session_id, SessionEvent.CANCELLED)

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(False, "cleanup failed", recovery_text="transcript"),
        )

        fake._stash_to_clipboard.assert_not_called()
        fake._on_fail.assert_not_called()

    def test_active_worker_failure_writes_recovery_once(self) -> None:
        fake, session_id = self._controller_at_inserting()

        Controller._on_process_complete(
            fake,
            session_id,
            ProcessResult(False, "cleanup failed", recovery_text="transcript"),
        )

        fake._stash_to_clipboard.assert_called_once_with("transcript")

    def test_unconfirmed_insert_failure_uses_neutral_user_message(self) -> None:
        fake = SimpleNamespace(
            log=Mock(), pill=Mock(), _beep_error=Mock()
        )

        with unittest.mock.patch("builtins.print") as print_message:
            Controller._on_fail(fake, "paste_unconfirmed")

        rendered = print_message.call_args.args[0]
        self.assertIn("text not safely inserted", rendered)
        self.assertNotIn("nothing inserted", rendered)


class WarmupTests(unittest.TestCase):
    def test_success_marks_both_backends_warm(self) -> None:
        fake = SimpleNamespace(
            _stt_lock=threading.Lock(),
            _cleanup_lock=threading.Lock(),
            stt=Mock(),
            cleaner=Mock(),
            _warmup_complete=False,
        )

        Controller.warmup(fake)

        self.assertTrue(fake._warmup_complete)
        fake.stt.load.assert_called_once_with()
        fake.cleaner.warmup.assert_called_once_with()

    def test_cleanup_failure_propagates_and_does_not_mark_warm(self) -> None:
        fake = SimpleNamespace(
            _stt_lock=threading.Lock(),
            _cleanup_lock=threading.Lock(),
            stt=Mock(),
            cleaner=Mock(),
            _warmup_complete=True,
        )
        fake.cleaner.warmup.side_effect = RuntimeError("cleanup unavailable")

        with self.assertRaisesRegex(RuntimeError, "cleanup unavailable"):
            Controller.warmup(fake)

        self.assertFalse(fake._warmup_complete)


class CancellationTests(unittest.TestCase):
    def test_processing_cancel_sets_event_before_worker_can_complete(self) -> None:
        sessions = SessionReducer()
        session = sessions.start()
        for event in (
            SessionEvent.RECORDING_STARTED,
            SessionEvent.RECORDING_STOPPED,
            SessionEvent.TRANSCRIPTION_STARTED,
        ):
            sessions.transition(session.session_id, event)
        fake = SimpleNamespace(
            state=PROCESSING,
            sessions=sessions,
            _pump=Mock(),
            hide_overlay=Mock(),
            recorder=Mock(),
            _beep_cancel=Mock(),
            log=Mock(),
        )

        Controller._on_cancel(fake)

        self.assertTrue(session.cancelled.is_set())
        self.assertEqual(fake.sessions.current.phase, SessionPhase.CANCELLED)
        fake.recorder.stop.assert_not_called()


class ProfileWiringTests(unittest.TestCase):
    def test_selected_profile_controls_transcriber_model_and_batch(self) -> None:
        cfg = SimpleNamespace(
            stt={"model": "tiny", "batch_size": 1, "min_duration_s": 0.1},
            performance={
                "profile": "quality",
                "streaming_enabled": False,
                "streaming_gate_passed": False,
            },
        )

        resolved = _resolved_stt_config(cfg)

        self.assertEqual(resolved["model"], "large-v3")
        self.assertEqual(resolved["batch_size"], 8)


if __name__ == "__main__":
    unittest.main()
