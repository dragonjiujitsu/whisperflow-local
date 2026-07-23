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

    def test_remote_cleanup_endpoint_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Cleaner({
                "provider": "openai-compatible",
                "model": "default",
                "prompt": "Clean only.",
                "base_url": "http://example.com:8888/v1",
                "api_key": "secret",
            })

    def test_cleanup_endpoint_rejects_credentials_query_and_fragment(self) -> None:
        invalid_urls = (
            "http://user:pass@127.0.0.1:8888/v1",
            "http://127.0.0.1:8888/v1?target=remote",
            "http://127.0.0.1:8888/v1#fragment",
            "https://127.0.0.1:8888/v1",
            "http://127.0.0.1:99999/v1",
        )
        for base_url in invalid_urls:
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                Cleaner({
                    "provider": "openai-compatible",
                    "model": "default",
                    "prompt": "Clean only.",
                    "base_url": base_url,
                    "api_key": "secret",
                })


if __name__ == "__main__":
    unittest.main()
