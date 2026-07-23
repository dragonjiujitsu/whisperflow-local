from __future__ import annotations

import unittest

from whisperflow_local.inserter import FocusTarget, Inserter
from whisperflow_local.platform.macos.pasteboard import PasteboardSnapshot


class FakeAccessibility:
    def __init__(self, values, matches=None) -> None:
        self._values = iter(values)
        self._matches = iter(matches or [True] * 20)

    def value(self, target):
        return next(self._values)

    def matches(self, target):
        return next(self._matches)


class FakePasteboard:
    def __init__(self) -> None:
        self.snapshot_value = PasteboardSnapshot((), 3)
        self.restores = []

    def snapshot(self):
        return self.snapshot_value

    def write_text(self, text):
        return 4

    def restore_if_unchanged(self, snapshot, expected):
        self.restores.append((snapshot, expected))
        return True


class FakeKeyboard:
    def press(self, key):
        pass

    def release(self, key):
        pass


class InserterConfirmationTests(unittest.TestCase):
    def make_inserter(self, values, *, matches=None, timeout=0.05):
        pasteboard = FakePasteboard()
        inserter = Inserter(
            {
                "mode": "paste",
                "settle_delay_s": 0.15,
                "confirmation_timeout_s": timeout,
                "press_enter_after": False,
            },
            pasteboard=pasteboard,
            accessibility=FakeAccessibility(values, matches),
        )
        inserter._kb = FakeKeyboard()
        return inserter, pasteboard

    def test_initially_unreadable_value_can_become_confirmation(self) -> None:
        inserter, pasteboard = self.make_inserter([None, None, "now readable"])
        ok, reason = inserter._paste("dictated", FocusTarget(pid=42))
        self.assertEqual((ok, reason), (True, "pasted"))
        self.assertEqual(pasteboard.restores, [(pasteboard.snapshot_value, 4)])

    def test_any_focused_value_change_confirms_without_substring_match(self) -> None:
        inserter, pasteboard = self.make_inserter(["before", "after"])
        ok, reason = inserter._paste("dictated", FocusTarget(pid=42))
        self.assertEqual((ok, reason), (True, "pasted"))
        self.assertEqual(pasteboard.restores, [(pasteboard.snapshot_value, 4)])

    def test_unconfirmed_paste_restores_clipboard_before_recovery(self) -> None:
        inserter, pasteboard = self.make_inserter(
            ["unchanged", "unchanged"], timeout=0
        )
        ok, reason = inserter._paste("dictated", FocusTarget(pid=42))
        self.assertEqual((ok, reason), (False, "paste_unconfirmed"))
        self.assertEqual(pasteboard.restores, [(pasteboard.snapshot_value, 4)])

    def test_focus_change_after_dispatch_still_restores_clipboard(self) -> None:
        inserter, pasteboard = self.make_inserter(
            ["before"], matches=[False]
        )
        ok, reason = inserter._paste("dictated", FocusTarget(pid=42))
        self.assertEqual((ok, reason), (False, "focus_changed_during_paste"))
        self.assertEqual(pasteboard.restores, [(pasteboard.snapshot_value, 4)])

    def test_legacy_settle_delay_is_used_as_confirmation_timeout(self) -> None:
        inserter = Inserter(
            {"mode": "paste", "settle_delay_s": 0.2},
            pasteboard=FakePasteboard(),
            accessibility=FakeAccessibility(["before", "after"]),
        )
        self.assertEqual(inserter._confirmation_timeout, 0.2)


if __name__ == "__main__":
    unittest.main()
