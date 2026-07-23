from __future__ import annotations

import unittest
from unittest.mock import patch

from whisperflow_local.cleanup import Cleaner


def config(provider: str = "openai-compatible") -> dict:
    return {
        "provider": provider,
        "model": "default",
        "prompt": "Clean only.",
        "max_expansion_ratio": 2.5,
        "options": {},
        "api_key": "configured-key",
        "api_key_env": "WHISPERFLOW_TEST_API_KEY",
        "base_url": "http://127.0.0.1:8888/v1",
    }


class CleanerSecurityTests(unittest.TestCase):
    def test_managed_cleaner_does_not_resolve_stored_credentials(self) -> None:
        with patch.dict(
            "os.environ", {"WHISPERFLOW_TEST_API_KEY": "environment-key"}
        ), patch(
            "whisperflow_local.keychain.KeychainSecretStore.get",
            side_effect=AssertionError("must not read Keychain"),
        ) as keychain_get:
            cleaner = Cleaner(config())

        self.assertEqual(cleaner._openai_api_key, "")
        keychain_get.assert_not_called()

    def test_clean_before_owned_runtime_key_makes_no_request(self) -> None:
        cleaner = Cleaner(config())

        with patch("whisperflow_local.cleanup.open_local_request") as open_request:
            with self.assertRaisesRegex(RuntimeError, "managed service is not READY"):
                cleaner.clean("private transcript")

        open_request.assert_not_called()

    def test_ollama_rejects_non_loopback_host_before_client_creation(self) -> None:
        with patch.dict(
            "os.environ", {"OLLAMA_HOST": "http://192.168.1.10:11434"}
        ), patch("whisperflow_local.cleanup.ollama.Client") as client:
            with self.assertRaisesRegex(ValueError, "OLLAMA_HOST"):
                Cleaner(config("ollama"))

        client.assert_not_called()

    def test_ollama_normalizes_localhost_and_pins_client_to_loopback(self) -> None:
        with patch.dict(
            "os.environ", {"OLLAMA_HOST": "localhost:11434"}
        ), patch("whisperflow_local.cleanup.ollama.Client") as client:
            Cleaner(config("ollama"), timeout_s=7.0)

        client.assert_called_once_with(
            host="http://127.0.0.1:11434", timeout=7.0
        )

    def test_removed_unsloth_cli_provider_is_rejected_at_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported cleanup provider"):
            Cleaner(config("unsloth-cli"))


if __name__ == "__main__":
    unittest.main()
