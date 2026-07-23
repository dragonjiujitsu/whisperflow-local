from __future__ import annotations

import subprocess
import threading
import unittest
from unittest.mock import patch

from whisperflow_local.cleanup import Cleaner, CleanupCancelled


def config(provider: str = "unsloth-cli") -> dict:
    return {
        "provider": provider,
        "fallback_provider": "unsloth-cli",
        "model": "default",
        "model_path": "/tmp/model.gguf",
        "prompt": "Clean only.",
        "max_expansion_ratio": 2.5,
        "options": {"temperature": 0.2, "num_predict": 32},
        "api_key": "local-key",
        "base_url": "http://127.0.0.1:8888/v1",
    }


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def communicate(self, timeout=None):
        raise subprocess.TimeoutExpired(["unsloth"], timeout)

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["unsloth"], timeout)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class CleanupCancellationTests(unittest.TestCase):
    def test_pre_cancelled_request_never_starts_provider(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        cleaner = Cleaner(config())
        with patch("whisperflow_local.cleanup.subprocess.Popen") as popen:
            with self.assertRaises(CleanupCancelled):
                cleaner.clean("hello", cancelled)
        popen.assert_not_called()

    def test_cancelled_cli_process_is_terminated(self) -> None:
        cancelled = threading.Event()
        process = FakeProcess()
        cleaner = Cleaner(config(), timeout_s=2.0)

        def cancel_soon() -> None:
            cancelled.wait(0.03)
            cancelled.set()

        # Set after Popen has begun; communicate's polling loop observes it.
        timer = threading.Timer(0.03, cancelled.set)
        timer.start()
        try:
            with patch("whisperflow_local.cleanup.shutil.which", return_value="/bin/unsloth"):
                with patch("whisperflow_local.cleanup.subprocess.Popen", return_value=process):
                    with self.assertRaises(CleanupCancelled):
                        cleaner.clean("hello", cancelled)
        finally:
            timer.cancel()
        self.assertTrue(process.terminated)

    def test_cancellation_does_not_trigger_fallback(self) -> None:
        cancelled = threading.Event()
        cleaner = Cleaner(config("openai-compatible"))
        with patch.object(
            cleaner, "_chat_openai_compatible",
            side_effect=CleanupCancelled("cancelled"),
        ), patch.object(cleaner, "_chat_unsloth_cli") as fallback:
            with self.assertRaises(CleanupCancelled):
                cleaner.clean("hello", cancelled)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
