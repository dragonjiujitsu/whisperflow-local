from __future__ import annotations

import unittest

from whisperflow_local.cleanup import Cleaner


class CleanerKeyRefreshTests(unittest.TestCase):
    def test_app_owned_service_can_refresh_generated_key(self) -> None:
        cleaner = Cleaner({
            "provider": "openai-compatible",
            "model": "default",
            "prompt": "Clean only.",
            "base_url": "http://127.0.0.1:8888/v1",
            "api_key": "",
            "api_key_env": "UNSET_TEST_KEY",
            "max_expansion_ratio": 2.5,
            "options": {},
        })
        cleaner.set_api_key("  sk-unsloth-generated  ")
        self.assertEqual(cleaner._openai_api_key, "sk-unsloth-generated")


if __name__ == "__main__":
    unittest.main()
