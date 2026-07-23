from __future__ import annotations

import unittest

from whisperflow_local.inserter import Inserter
from whisperflow_local.platform.macos.pasteboard import PasteboardSnapshot


class FakeKeyboard:
    def __init__(self) -> None:
        self.actions = []

    def press(self, key) -> None:
        self.actions.append(("press", key))

    def release(self, key) -> None:
        self.actions.append(("release", key))

    def tap(self, key) -> None:
        self.actions.append(("tap", key))


class FakePasteboard:
    def __init__(self, fail_write: bool = False) -> None:
        self.snapshot_value = PasteboardSnapshot((), 2)
        self.text = None
        self.restored = None
        self.fail_write = fail_write

    def snapshot(self):
        return self.snapshot_value

    def write_text(self, text: str) -> int:
        if self.fail_write:
            raise RuntimeError("unavailable")
        self.text = text
        return 4

    def restore_if_unchanged(self, snapshot, expected_change_count):
        self.restored = (snapshot, expected_change_count)
        return True


class InserterPasteboardTests(unittest.TestCase):
    def make_inserter(self, pasteboard: FakePasteboard) -> Inserter:
        inserter = Inserter(
            {"mode": "paste", "settle_delay_s": 0, "press_enter_after": False},
            pasteboard=pasteboard,
        )
        inserter._kb = FakeKeyboard()
        return inserter

    def test_paste_uses_transaction_and_restores_snapshot(self) -> None:
        pasteboard = FakePasteboard()
        inserter = self.make_inserter(pasteboard)
        ok, reason = inserter._paste("dictated text")
        self.assertTrue(ok)
        self.assertEqual(reason, "pasted")
        self.assertEqual(pasteboard.text, "dictated text")
        self.assertEqual(pasteboard.restored, (pasteboard.snapshot_value, 4))
        self.assertEqual(len(inserter._kb.actions), 4)

    def test_pasteboard_failure_does_not_press_keys(self) -> None:
        pasteboard = FakePasteboard(fail_write=True)
        inserter = self.make_inserter(pasteboard)
        ok, reason = inserter._paste("dictated text")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("pasteboard_unavailable:"))
        self.assertEqual(inserter._kb.actions, [])
        self.assertIsNone(pasteboard.restored)


if __name__ == "__main__":
    unittest.main()
