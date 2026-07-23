from __future__ import annotations

import io
import unittest

from whisperflow_local.service import (
    LocalServiceManager,
    ServiceState,
    build_unsloth_command,
)


def cleanup_config() -> dict:
    return {
        "base_url": "http://127.0.0.1:8888/v1",
        "server_model": "unsloth/Qwen-GGUF",
        "server_gguf_variant": "UD-Q4_K_XL",
    }


class FakeSecrets:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.saved = []

    def get(self, account):
        return self.value

    def set(self, account, value):
        self.value = value
        self.saved.append((account, value))


class FakeProcess:
    def __init__(self, output: str = "") -> None:
        self.stdout = io.StringIO(output)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode or 0

    def kill(self):
        self.killed = True
        self.returncode = -9


class ServiceTests(unittest.TestCase):
    def test_command_is_loopback_and_disables_tools(self) -> None:
        command = build_unsloth_command(cleanup_config())
        self.assertEqual(command[:3], ["unsloth", "run", "--model"])
        self.assertIn("127.0.0.1", command)
        self.assertIn("8888", command)
        self.assertIn("--disable-tools", command)
        self.assertEqual(
            command[-2:], ["--gguf-variant", "UD-Q4_K_XL"]
        )

    def test_connects_without_owning_existing_service(self) -> None:
        secrets = FakeSecrets("stored-key")
        calls = []
        manager = LocalServiceManager(
            cleanup_config(), secrets,
            popen=lambda *a, **k: calls.append((a, k)),
            probe=lambda key: key == "stored-key",
        )
        health = manager.connect_or_start(timeout_s=0.1)
        self.assertEqual(health.state, ServiceState.READY)
        self.assertFalse(health.owned)
        self.assertEqual(calls, [])

    def test_started_service_key_is_captured_and_saved(self) -> None:
        secrets = FakeSecrets()
        process = FakeProcess("API key: sk-unsloth-generated_123\n")
        probes = []

        def probe(key):
            probes.append(key)
            return key == "sk-unsloth-generated_123"

        manager = LocalServiceManager(
            cleanup_config(), secrets,
            popen=lambda *a, **k: process,
            probe=probe,
        )
        health = manager.connect_or_start(timeout_s=1.0)
        self.assertEqual(health.state, ServiceState.READY)
        self.assertTrue(health.owned)
        self.assertEqual(health.api_key, "sk-unsloth-generated_123")
        self.assertEqual(secrets.value, "sk-unsloth-generated_123")

    def test_stop_never_terminates_unowned_service(self) -> None:
        process = FakeProcess()
        manager = LocalServiceManager(
            cleanup_config(), FakeSecrets("key"),
            popen=lambda *a, **k: process,
            probe=lambda key: True,
        )
        manager.connect_or_start(timeout_s=0.1)
        manager.stop()
        self.assertFalse(process.terminated)

    def test_stop_terminates_owned_service(self) -> None:
        process = FakeProcess("sk-unsloth-generated\n")
        manager = LocalServiceManager(
            cleanup_config(), FakeSecrets(),
            popen=lambda *a, **k: process,
            probe=lambda key: True,
        )
        manager.connect_or_start(timeout_s=1.0)
        # Make it look running again after readiness.
        process.returncode = None
        manager.stop()
        self.assertTrue(process.terminated)
        self.assertEqual(manager.health.state, ServiceState.STOPPED)


if __name__ == "__main__":
    unittest.main()
