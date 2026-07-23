from __future__ import annotations

import unittest

from whisperflow_local.session import (
    DictationSession,
    SessionEvent,
    SessionPhase,
    SessionReducer,
)


class SessionReducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reducer = SessionReducer()

    def test_happy_path_reaches_ready(self) -> None:
        session = self.reducer.start()
        self.assertEqual(session.phase, SessionPhase.STARTING)
        for event, phase in (
            (SessionEvent.RECORDING_STARTED, SessionPhase.RECORDING),
            (SessionEvent.RECORDING_STOPPED, SessionPhase.FINALIZING),
            (SessionEvent.TRANSCRIPTION_STARTED, SessionPhase.TRANSCRIBING),
            (SessionEvent.TRANSCRIPTION_FINISHED, SessionPhase.CLEANING),
            (SessionEvent.CLEANUP_FINISHED, SessionPhase.INSERTING),
            (SessionEvent.INSERTION_FINISHED, SessionPhase.READY),
        ):
            session = self.reducer.transition(session.session_id, event)
            self.assertEqual(session.phase, phase)

    def test_new_session_invalidates_old_results(self) -> None:
        old = self.reducer.start()
        new = self.reducer.start()
        self.assertGreater(new.session_id, old.session_id)
        stale = self.reducer.transition(
            old.session_id, SessionEvent.RECORDING_STARTED
        )
        self.assertIs(stale, new)
        self.assertEqual(stale.phase, SessionPhase.STARTING)

    def test_cancel_is_terminal_for_that_session(self) -> None:
        session = self.reducer.start()
        session = self.reducer.transition(
            session.session_id, SessionEvent.RECORDING_STARTED
        )
        cancelled = self.reducer.transition(
            session.session_id, SessionEvent.CANCELLED
        )
        self.assertEqual(cancelled.phase, SessionPhase.CANCELLED)
        ignored = self.reducer.transition(
            session.session_id, SessionEvent.RECORDING_STOPPED
        )
        self.assertIs(ignored, cancelled)

    def test_illegal_transition_raises(self) -> None:
        session = self.reducer.start()
        with self.assertRaises(ValueError):
            self.reducer.transition(
                session.session_id, SessionEvent.CLEANUP_FINISHED
            )

    def test_failure_preserves_typed_reason(self) -> None:
        session = self.reducer.start()
        failed = self.reducer.fail(session.session_id, "microphone_unavailable")
        self.assertEqual(failed.phase, SessionPhase.ERROR)
        self.assertEqual(failed.reason, "microphone_unavailable")

    def test_session_cancel_flag_is_shared_with_workers(self) -> None:
        session = self.reducer.start()
        self.assertFalse(session.cancelled.is_set())
        self.reducer.transition(session.session_id, SessionEvent.CANCELLED)
        self.assertTrue(session.cancelled.is_set())

    def test_snapshot_is_immutable(self) -> None:
        session = self.reducer.start()
        self.assertIsInstance(session, DictationSession)
        with self.assertRaises(Exception):
            session.phase = SessionPhase.READY  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
