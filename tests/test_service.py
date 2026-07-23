from __future__ import annotations

import io
import queue
import socket
import threading
import unittest
from unittest.mock import patch

from whisperflow_local.service import (
    LocalServiceManager,
    ServiceState,
    build_unsloth_command,
    resolve_unsloth_executable,
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


class FailingSecrets(FakeSecrets):
    def set(self, account, value):
        raise RuntimeError("keychain unavailable")


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
        command = build_unsloth_command(
            cleanup_config(), executable="/opt/unsloth/bin/unsloth"
        )
        self.assertEqual(
            command[:3], ["/opt/unsloth/bin/unsloth", "run", "--model"]
        )
        self.assertIn("127.0.0.1", command)
        self.assertIn("8888", command)
        self.assertIn("--disable-tools", command)
        self.assertEqual(
            command[-2:], ["--gguf-variant", "UD-Q4_K_XL"]
        )

    def test_executable_is_resolved_before_command_construction(self) -> None:
        with patch(
            "whisperflow_local.service.shutil.which",
            return_value="/opt/unsloth/bin/../bin/unsloth",
        ):
            executable = resolve_unsloth_executable()

        self.assertEqual(executable, "/opt/unsloth/bin/unsloth")

    def test_stored_key_never_authorizes_preexisting_service(self) -> None:
        secrets = FakeSecrets("stored-key")
        calls = []
        process = FakeProcess("API key: sk-unsloth-owned\n")
        manager = LocalServiceManager(
            cleanup_config(), secrets,
            popen=lambda *a, **k: calls.append((a, k)) or process,
            probe=lambda key: key == "sk-unsloth-owned",
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )
        health = manager.connect_or_start(timeout_s=1.0)
        self.assertEqual(health.state, ServiceState.READY)
        self.assertTrue(health.owned)
        self.assertEqual(health.api_key, "sk-unsloth-owned")
        self.assertEqual(len(calls), 1)

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
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )
        health = manager.connect_or_start(timeout_s=1.0)
        self.assertEqual(health.state, ServiceState.READY)
        self.assertTrue(health.owned)
        self.assertEqual(health.api_key, "sk-unsloth-generated_123")
        self.assertEqual(secrets.value, "sk-unsloth-generated_123")

    def test_keychain_failure_keeps_owned_child_ready_with_runtime_key(self) -> None:
        process = FakeProcess("API key: sk-unsloth-in-memory\n")
        manager = LocalServiceManager(
            cleanup_config(), FailingSecrets(),
            popen=lambda *a, **k: process,
            probe=lambda key: key == "sk-unsloth-in-memory",
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )

        health = manager.connect_or_start(timeout_s=1.0)

        self.assertEqual(health.state, ServiceState.READY)
        self.assertTrue(health.owned)
        self.assertEqual(health.api_key, "sk-unsloth-in-memory")
        self.assertFalse(process.terminated)
        self.assertNotIn(health.api_key, health.detail)

    def test_stop_terminates_owned_service(self) -> None:
        process = FakeProcess("sk-unsloth-generated\n")
        manager = LocalServiceManager(
            cleanup_config(), FakeSecrets(),
            popen=lambda *a, **k: process,
            probe=lambda key: True,
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )
        manager.connect_or_start(timeout_s=1.0)
        # Make it look running again after readiness.
        process.returncode = None
        manager.stop()
        self.assertTrue(process.terminated)
        self.assertEqual(manager.health.state, ServiceState.STOPPED)

    def test_repeated_connect_is_single_flight_for_ready_owned_process(self) -> None:
        process = FakeProcess("sk-unsloth-generated\n")
        starts = []
        manager = LocalServiceManager(
            cleanup_config(), FakeSecrets(),
            popen=lambda *a, **k: starts.append(1) or process,
            probe=lambda key: True,
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )
        first = manager.connect_or_start(timeout_s=1.0)
        second = manager.connect_or_start(timeout_s=1.0)
        self.assertEqual(first, second)
        self.assertEqual(starts, [1])

    def test_stdout_drain_is_bounded(self) -> None:
        lines: queue.Queue[str] = queue.Queue(maxsize=4)
        LocalServiceManager._read_lines(
            io.StringIO("".join(f"line-{index}\n" for index in range(20))),
            lines,
        )
        self.assertEqual(lines.qsize(), 4)

    def test_stop_requested_during_start_terminates_owned_child(self) -> None:
        process = FakeProcess()
        started = threading.Event()

        def popen(*args, **kwargs):
            started.set()
            return process

        manager = LocalServiceManager(
            cleanup_config(), FakeSecrets(), popen=popen, probe=lambda key: False,
            port_available=lambda: True,
            executable="/opt/unsloth/bin/unsloth",
        )
        worker = threading.Thread(
            target=manager.connect_or_start, kwargs={"timeout_s": 2.0}
        )
        worker.start()
        self.assertTrue(started.wait(0.5))
        manager.stop()
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(process.terminated)
        self.assertEqual(manager.health.state, ServiceState.STOPPED)

    def test_command_rejects_non_loopback_endpoint(self) -> None:
        config = cleanup_config()
        config["base_url"] = "http://example.com:8888/v1"
        with self.assertRaises(ValueError):
            build_unsloth_command(
                config, executable="/opt/unsloth/bin/unsloth"
            )

    def test_preexisting_listener_is_refused_before_process_start(self) -> None:
        starts = []
        manager = LocalServiceManager(
            cleanup_config(),
            FakeSecrets("stored-key"),
            popen=lambda *a, **k: starts.append(1),
            probe=lambda key: True,
            port_available=lambda: False,
            executable="/opt/unsloth/bin/unsloth",
        )
        health = manager.connect_or_start(timeout_s=0.1)
        self.assertEqual(health.state, ServiceState.ERROR)
        self.assertIn("pre-existing listener", health.detail)
        self.assertEqual(starts, [])

    def test_real_occupied_loopback_socket_is_refused(self) -> None:
        starts = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            config = cleanup_config()
            config["base_url"] = f"http://127.0.0.1:{port}/v1"
            manager = LocalServiceManager(
                config,
                FakeSecrets(),
                popen=lambda *args, **kwargs: starts.append((args, kwargs)),
                probe=lambda key: True,
            )
            health = manager.connect_or_start(timeout_s=0.1)

        self.assertEqual(health.state, ServiceState.ERROR)
        self.assertIn("pre-existing listener", health.detail)
        self.assertEqual(starts, [])


if __name__ == "__main__":
    unittest.main()
