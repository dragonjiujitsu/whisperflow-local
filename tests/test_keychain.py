from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whisperflow_local.keychain import KeychainSecretStore


class KeychainTests(unittest.TestCase):
    def test_get_returns_secret_without_newline(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="secret\n")
        with patch("whisperflow_local.keychain.subprocess.run", return_value=result) as run:
            value = KeychainSecretStore("test.service").get("account")
        self.assertEqual(value, "secret")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["security", "find-generic-password"])
        self.assertNotIn("secret", command)

    def test_missing_secret_returns_empty_string(self) -> None:
        result = SimpleNamespace(returncode=44, stdout="")
        with patch("whisperflow_local.keychain.subprocess.run", return_value=result):
            self.assertEqual(KeychainSecretStore().get("missing"), "")

    def test_set_uses_update_semantics(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="")
        with patch("whisperflow_local.keychain.subprocess.run", return_value=result) as run:
            KeychainSecretStore("test.service").set("account", "secret")
        command = run.call_args.args[0]
        self.assertIn("-U", command)
        self.assertEqual(command[-1], "secret")
        self.assertTrue(run.call_args.kwargs["check"])

    def test_empty_secret_is_rejected_without_command(self) -> None:
        with patch("whisperflow_local.keychain.subprocess.run") as run:
            with self.assertRaises(ValueError):
                KeychainSecretStore().set("account", "")
        run.assert_not_called()

    def test_delete_reports_security_result(self) -> None:
        with patch(
            "whisperflow_local.keychain.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ):
            self.assertTrue(KeychainSecretStore().delete("account"))


if __name__ == "__main__":
    unittest.main()
