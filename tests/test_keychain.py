from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whisperflow_local.keychain import KeychainSecretStore, _SecurityFrameworkAdapter


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

    def test_set_uses_in_process_security_adapter(self) -> None:
        adapter = unittest.mock.Mock()
        with patch("whisperflow_local.keychain.subprocess.run") as run:
            KeychainSecretStore("test.service", security=adapter).set(
                "account", "secret"
            )
        adapter.set_generic_password.assert_called_once_with(
            "test.service", "account", "secret"
        )
        run.assert_not_called()

    def test_empty_secret_is_rejected_without_command(self) -> None:
        adapter = unittest.mock.Mock()
        with patch("whisperflow_local.keychain.subprocess.run") as run:
            with self.assertRaises(ValueError):
                KeychainSecretStore(security=adapter).set("account", "")
        run.assert_not_called()
        adapter.set_generic_password.assert_not_called()

    def test_security_adapter_updates_then_adds_when_missing(self) -> None:
        calls = []

        class FakeData:
            @staticmethod
            def dataWithBytes_length_(value, length):
                return value[:length]

        def update(query, values):
            calls.append(("update", query, values))
            return _SecurityFrameworkAdapter._ITEM_NOT_FOUND

        def add(values, result):
            calls.append(("add", values, result))
            return 0

        adapter = _SecurityFrameworkAdapter.__new__(_SecurityFrameworkAdapter)
        adapter._data_type = FakeData
        adapter._symbols = {
            "kSecClass": "class",
            "kSecClassGenericPassword": "generic",
            "kSecAttrService": "service",
            "kSecAttrAccount": "account",
            "kSecValueData": "value",
            "SecItemUpdate": update,
            "SecItemAdd": add,
        }
        adapter.set_generic_password("test.service", "user", "secret")
        self.assertEqual(calls[0][0], "update")
        self.assertEqual(calls[1][0], "add")
        self.assertEqual(calls[1][1]["value"], b"secret")

    def test_delete_reports_security_result(self) -> None:
        with patch(
            "whisperflow_local.keychain.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ):
            self.assertTrue(KeychainSecretStore().delete("account"))


if __name__ == "__main__":
    unittest.main()
