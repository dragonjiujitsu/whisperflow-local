import tempfile
import time
import unittest
from pathlib import Path

from whisperflow_local.history import HistoryStore


class HistoryTests(unittest.TestCase):
    def test_disabled_history_never_creates_content_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            store = HistoryStore(path)
            self.assertIsNone(store.add("private words"))
            self.assertFalse(path.exists())

    def test_retention_delete_one_export_and_delete_all(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            store = HistoryStore(path, enabled=True, retention_days=7)
            now = time.time()
            store.add("old", now=now - 8 * 86400)
            current = store.add("current", now=now)
            self.assertEqual([item.text for item in store.list(now=now)], ["current"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            destination = Path(temp) / "export.json"
            store.export_to(destination)
            self.assertIn("current", destination.read_text())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            store.delete(current.entry_id)
            self.assertEqual(store.list(now=now), [])
            store.add("again", now=now)
            store.delete_all()
            self.assertFalse(path.exists())

    def test_corrupt_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            path.write_text("not json")
            self.assertEqual(HistoryStore(path, enabled=True).list(), [])


if __name__ == "__main__":
    unittest.main()
