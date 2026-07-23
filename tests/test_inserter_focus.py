from __future__ import annotations

import unittest

from whisperflow_local.inserter import FocusTarget, Inserter
from whisperflow_local.platform.macos.pasteboard import PasteboardSnapshot


class FakeAccessibility:
    def __init__(self, matches: list[bool]) -> None:
        self.results = iter(matches)
        self.calls = 0

    def matches(self, target) -> bool:
        self.calls += 1
        return next(self.results)


class FakePasteboard:
    def __init__(self) -> None:
        self.writes = []
        self.restores = 0

    def snapshot(self):
        return PasteboardSnapshot((), 1)

    def write_text(self, text):
        self.writes.append(text)
        return 2

    def restore_if_unchanged(self, snapshot, expected):
        self.restores += 1
        return True


class FakeKeyboard:
    def __init__(self) -> None:
        self.actions = []

    def press(self, key):
        self.actions.append(("press", key))

    def release(self, key):
        self.actions.append(("release", key))

    def tap(self, key):
        self.actions.append(("tap", key))


class InserterFocusTests(unittest.TestCase):
    def make_inserter(self, matches, press_enter=False):
        pasteboard = FakePasteboard()
        accessibility = FakeAccessibility(matches)
        inserter = Inserter(
            {
                "mode": "paste",
                "settle_delay_s": 0,
                "press_enter_after": press_enter,
            },
            pasteboard=pasteboard,
            accessibility=accessibility,
        )
        keyboard = FakeKeyboard()
        inserter._kb = keyboard
        return inserter, pasteboard, accessibility, keyboard

    def test_changed_focused_element_aborts_before_clipboard_write(self) -> None:
        inserter, pasteboard, accessibility, keyboard = self.make_inserter([False])
        target = FocusTarget(pid=42, native=True, element=object())
        ok, reason = inserter.insert("hello", target)
        self.assertFalse(ok)
        self.assertEqual(reason, "focus_changed")
        self.assertEqual(pasteboard.writes, [])
        self.assertEqual(keyboard.actions, [])
        self.assertEqual(accessibility.calls, 1)

    def test_target_is_revalidated_before_optional_submit(self) -> None:
        inserter, pasteboard, accessibility, keyboard = self.make_inserter(
            [True, False], press_enter=True
        )
        target = FocusTarget(pid=42, native=True, element=object())
        ok, reason = inserter.insert("hello", target)
        self.assertTrue(ok)
        self.assertEqual(reason, "pasted")
        self.assertEqual(pasteboard.writes, ["hello"])
        self.assertEqual(accessibility.calls, 2)
        self.assertFalse(any(action[0] == "tap" for action in keyboard.actions))


if __name__ == "__main__":
    unittest.main()
