import unittest

from whisperflow_local.profiles import resolve_writing_mode


class WritingProfileTests(unittest.TestCase):
    def test_per_app_override_wins(self):
        selected = resolve_writing_mode("natural", "com.apple.mail", {"com.apple.mail": "email"})
        self.assertEqual(selected.key, "email")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            resolve_writing_mode("invent", None, {})


if __name__ == "__main__":
    unittest.main()
