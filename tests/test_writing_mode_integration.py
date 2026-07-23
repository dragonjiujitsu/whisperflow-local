import unittest
from unittest.mock import patch

from whisperflow_local.cleanup import Cleaner


class WritingModeIntegrationTests(unittest.TestCase):
    def test_mode_is_appended_to_trusted_system_message_not_transcript(self):
        cleaner = Cleaner({
            "provider": "openai-compatible", "model": "local", "prompt": "base guard",
            "api_key": "local-key", "max_expansion_ratio": 3,
        })
        with patch.object(cleaner, "_chat_openai_compatible", return_value="hello") as call:
            result = cleaner.clean("hello", instruction="Format as an email.")
        self.assertEqual(result, "hello")
        self.assertEqual(call.call_args.args[0], "hello")
        self.assertIn("Format as an email", call.call_args.kwargs["system"])
        self.assertNotIn("Format as an email", call.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
