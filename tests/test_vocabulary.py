import json
import tempfile
import unittest
from pathlib import Path

from whisperflow_local.vocabulary import VocabularyData, VocabularyStore


class VocabularyTests(unittest.TestCase):
    def test_apply_round_trip_export_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            store = VocabularyStore(Path(temp) / "vocabulary.json")
            data = VocabularyData(("Kaden",), (("caden", "Kaden"),))
            store.save(data)
            self.assertEqual(store.load().apply("hello caden"), "hello Kaden")
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            exported = Path(temp) / "export.json"
            store.export_to(exported)
            self.assertIn("Kaden", exported.read_text())
            store.delete_all()
            self.assertFalse(store.path.exists())

    def test_case_insensitive_collision_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = VocabularyStore(Path(temp) / "vocabulary.json")
            with self.assertRaises(ValueError):
                store.save(VocabularyData(replacements=(("abc", "A"), ("ABC", "B"))))


if __name__ == "__main__":
    unittest.main()
