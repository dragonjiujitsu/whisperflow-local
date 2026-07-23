from __future__ import annotations

import unittest

from whisperflow_local.platform.macos.pasteboard import (
    MacPasteboard,
    PasteboardItem,
    PasteboardSnapshot,
)


class FakeData(bytes):
    pass


class FakeSourceItem:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values

    def types(self):
        return list(self.values)

    def dataForType_(self, type_name):
        return FakeData(self.values[type_name])


class FakePasteboard:
    def __init__(self) -> None:
        self.count = 4
        self.items = [
            FakeSourceItem({"public.utf8-plain-text": b"old"}),
            FakeSourceItem({"public.png": b"png-bytes"}),
        ]
        self.text = ""
        self.written = None

    def changeCount(self):
        return self.count

    def pasteboardItems(self):
        return self.items

    def clearContents(self):
        self.count += 1
        self.items = []

    def setString_forType_(self, text, type_name):
        self.text = text
        self.count += 1
        return True

    def writeObjects_(self, objects):
        self.written = objects
        self.count += 1
        return True


class PasteboardTests(unittest.TestCase):
    def test_snapshot_preserves_multiple_items_and_types(self) -> None:
        backend = FakePasteboard()
        snapshot = MacPasteboard(backend).snapshot()
        self.assertEqual(snapshot.change_count, 4)
        self.assertEqual(len(snapshot.items), 2)
        self.assertEqual(
            snapshot.items[1].values, (("public.png", b"png-bytes"),)
        )

    def test_write_returns_expected_change_count(self) -> None:
        backend = FakePasteboard()
        change_count = MacPasteboard(backend).write_text("new")
        self.assertEqual(backend.text, "new")
        self.assertEqual(change_count, backend.changeCount())

    def test_restore_refuses_to_overwrite_external_change(self) -> None:
        backend = FakePasteboard()
        adapter = MacPasteboard(backend)
        snapshot = adapter.snapshot()
        expected = adapter.write_text("dictation")
        backend.count += 1
        self.assertFalse(adapter.restore_if_unchanged(snapshot, expected))
        self.assertIsNone(backend.written)

    def test_empty_snapshot_clears_temporary_text(self) -> None:
        backend = FakePasteboard()
        adapter = MacPasteboard(backend)
        snapshot = PasteboardSnapshot((), backend.changeCount())
        expected = adapter.write_text("dictation")
        self.assertTrue(adapter.restore_if_unchanged(snapshot, expected))
        self.assertEqual(backend.items, [])

    def test_snapshot_value_objects_are_immutable(self) -> None:
        item = PasteboardItem((("public.text", b"hello"),))
        snapshot = PasteboardSnapshot((item,), 1)
        with self.assertRaises(Exception):
            snapshot.change_count = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
