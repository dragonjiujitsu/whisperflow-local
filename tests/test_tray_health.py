from __future__ import annotations

import unittest

from whisperflow_local.tray import update_tray_status


class FakeAction:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class FakeTray:
    def __init__(self) -> None:
        self._status_action = FakeAction()
        self.tooltip = ""

    def setToolTip(self, value: str) -> None:
        self.tooltip = value


class TrayHealthTests(unittest.TestCase):
    def test_status_updates_menu_and_tooltip(self) -> None:
        tray = FakeTray()
        update_tray_status(tray, "degraded", "direct local fallback")
        self.assertEqual(
            tray._status_action.text,
            "Degraded · direct local fallback",
        )
        self.assertIn("degraded", tray.tooltip)
        self.assertIn("direct local fallback", tray.tooltip)

    def test_status_without_detail_is_concise(self) -> None:
        tray = FakeTray()
        update_tray_status(tray, "ready")
        self.assertEqual(tray._status_action.text, "Ready")


if __name__ == "__main__":
    unittest.main()
