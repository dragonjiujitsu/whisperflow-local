import unittest
from unittest.mock import Mock

from whisperflow_local.platform.macos.power import MacPowerMonitor
from whisperflow_local.app import Controller, RECORDING
from whisperflow_local.session import SessionEvent, SessionPhase, SessionReducer


class FakeCenter:
    def __init__(self): self.added = []; self.removed = []
    def addObserver_selector_name_object_(self, *args): self.added.append(args)
    def removeObserver_(self, observer): self.removed.append(observer)


class PowerMonitorTests(unittest.TestCase):
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
