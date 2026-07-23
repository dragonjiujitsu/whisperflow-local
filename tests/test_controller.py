from __future__ import annotations

import threading
import time
import unittest

from whisperflow_local.app import ProcessResult, _locked_call, _with_timeout
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

    def test_backend_lock_prevents_overlap_after_timeout(self) -> None:
        lock = threading.Lock()
        release = threading.Event()
        active = 0
        peak = 0
        guard = threading.Lock()

        def work(wait: bool) -> str:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            if wait:
                release.wait(0.5)
            with guard:
                active -= 1
            return "ok"

        first_done, _ = _with_timeout(
            lambda: _locked_call(lock, work, True), 0.01, "timeout"
        )
        self.assertFalse(first_done)
        second_result: list[tuple[bool, str]] = []
        second = threading.Thread(
            target=lambda: second_result.append(
                _with_timeout(
                    lambda: _locked_call(lock, work, False), 0.4, "timeout"
                )
            )
        )
        second.start()
        time.sleep(0.03)
        self.assertEqual(peak, 1)
        release.set()
        second.join(0.5)
        self.assertEqual(second_result, [(True, "ok")])
        self.assertEqual(peak, 1)


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


if __name__ == "__main__":
    unittest.main()
