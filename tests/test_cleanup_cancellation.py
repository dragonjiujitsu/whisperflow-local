from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from whisperflow_local.cleanup import Cleaner, CleanupCancelled


def config(provider: str = "openai-compatible") -> dict:
    return {
        "provider": provider,
        "model": "default",
        "prompt": "Clean only.",
        "max_expansion_ratio": 2.5,
        "options": {"temperature": 0.2, "num_predict": 32},
        "api_key": "local-key",
        "base_url": "http://127.0.0.1:8888/v1",
    }


class CleanupCancellationTests(unittest.TestCase):
    def test_pre_cancelled_request_never_starts_provider(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        cleaner = Cleaner(config())
        with patch.object(cleaner, "_chat_openai_compatible") as chat:
            with self.assertRaises(CleanupCancelled):
                cleaner.clean("hello", cancelled)
        chat.assert_not_called()

    def test_provider_cancellation_is_propagated(self) -> None:
        cancelled = threading.Event()
        cleaner = Cleaner(config("openai-compatible"))
        with patch.object(
            cleaner, "_chat_openai_compatible",
            side_effect=CleanupCancelled("cancelled"),
        ):
            with self.assertRaises(CleanupCancelled):
                cleaner.clean("hello", cancelled)


if __name__ == "__main__":
    unittest.main()
