import unittest
import threading
from unittest.mock import Mock

from whisperflow_local.__main__ import _WarmupFlight, _warm_runtime
from whisperflow_local.platform.macos.power import MacPowerMonitor
from whisperflow_local.app import Controller, RECORDING
from whisperflow_local.session import SessionEvent, SessionPhase, SessionReducer


class FakeCenter:
    def __init__(self): self.added = []; self.removed = []
    def addObserver_selector_name_object_(self, *args): self.added.append(args)
    def removeObserver_(self, observer): self.removed.append(observer)


class PowerMonitorTests(unittest.TestCase):
    def test_warmup_exception_returns_terminal_error_health(self):
        ctrl = Mock()
        ctrl.warmup.side_effect = RuntimeError("model unavailable")

        state, detail = _warm_runtime(ctrl, None, {"value": "fallback"})

        self.assertEqual(state, "error")
        self.assertIn("RuntimeError", detail)

    def test_warmup_refuses_ready_service_without_verified_ownership(self):
        ctrl = Mock()
        manager = Mock()
        manager.connect_or_start.return_value = Mock(
            state=Mock(value="ready"),
            owned=False,
            api_key="untrusted-key",
            detail="unexpected listener",
        )

        state, detail = _warm_runtime(ctrl, manager, {"value": "starting"})

        self.assertEqual(state, "error")
        self.assertIn("ownership", detail)
        ctrl.cleaner.set_api_key.assert_not_called()

    def test_warmup_flight_rejects_wake_fanout_until_current_run_finishes(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def warmup():
            calls.append("run")
            started.set()
            release.wait(0.5)

        flight = _WarmupFlight(warmup)
        self.assertTrue(flight.start("initial-warmup"))
        self.assertTrue(started.wait(0.2))
        self.assertFalse(flight.start("wake-warmup"))
        release.set()
        self.assertTrue(flight.wait(0.5))
        self.assertEqual(calls, ["run"])

    def test_registration_is_idempotent_and_removable(self):
        monitor = MacPowerMonitor(lambda event: None)
        monitor._center = FakeCenter()
        monitor.start(); monitor.start()
        self.assertEqual(len(monitor._center.added), 2)
        monitor.stop()
        self.assertEqual(len(monitor._center.removed), 1)

    def test_sleep_cancels_recording_and_stops_audio(self):
        class FakeController:
            state = RECORDING
            sessions = SessionReducer()
            recorder = Mock(); _pump = Mock(); hide_overlay = Mock()
            health_signal = Mock(); log = Mock()
        fake = FakeController()
        session = fake.sessions.start()
        fake.sessions.transition(session.session_id, SessionEvent.RECORDING_STARTED)
        Controller._on_interrupt(fake, "sleep")
        self.assertEqual(fake.sessions.current.phase, SessionPhase.CANCELLED)
        fake.recorder.stop.assert_called_once()
        fake.health_signal.emit.assert_called_with("degraded", "interrupted: sleep")


if __name__ == "__main__": unittest.main()
