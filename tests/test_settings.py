from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local.paths import AppPaths
from whisperflow_local.settings import SETTINGS_VERSION, SettingsError, SettingsStore

ROOT = Path(__file__).resolve().parents[1]


class SettingsTests(unittest.TestCase):
    def make_store(self, temp: str) -> SettingsStore:
        return SettingsStore(
            ROOT / "config.yaml", AppPaths.discover(Path(temp))
        )

    def test_load_without_user_file_returns_valid_bundled_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = self.make_store(temp).load()
            self.assertEqual(settings["hotkey"]["combo"], "<cmd>+<shift>+<space>")
            self.assertEqual(settings["audio"]["sample_rate"], 16000)
            self.assertEqual(settings["insert"]["confirmation_timeout_s"], 0.75)
            self.assertNotIn("settle_delay_s", settings["insert"])
            for obsolete in (
                "fallback_provider", "api_key", "api_key_env",
                "api_key_keychain_account",
            ):
                self.assertNotIn(obsolete, settings["cleanup"])

    def test_user_overrides_deep_merge_without_losing_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            store.save_overrides({"audio": {"max_seconds": 120}})
            loaded = store.load()
            self.assertEqual(loaded["audio"]["max_seconds"], 120)
            self.assertEqual(loaded["audio"]["sample_rate"], 16000)
            payload = json.loads(store.paths.settings.read_text())
            self.assertEqual(payload["schema_version"], SETTINGS_VERSION)

    def test_saved_settings_are_private_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            store.save_overrides({"overlay": {"enabled": False}})
            self.assertEqual(store.paths.settings.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(store.paths.settings.parent.glob(".settings-*")))

    def test_atomic_replace_failure_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            store.save_overrides({"audio": {"max_seconds": 100}})
            before = store.paths.settings.read_bytes()
            with patch("whisperflow_local.settings.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    store.save_overrides({"audio": {"max_seconds": 200}})
            self.assertEqual(store.paths.settings.read_bytes(), before)
            self.assertFalse(list(store.paths.settings.parent.glob(".settings-*")))

    def test_invalid_range_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            with self.assertRaisesRegex(SettingsError, "audio.max_seconds"):
                store.save_overrides({"audio": {"max_seconds": 0}})
            self.assertFalse(store.paths.settings.exists())

    def test_remote_cleanup_endpoint_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            with self.assertRaisesRegex(SettingsError, "loopback"):
                store.save_overrides({
                    "cleanup": {"base_url": "http://example.com:8888/v1"}
                })
            self.assertFalse(store.paths.settings.exists())

    def test_optional_paste_confirmation_timeout_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            store.save_overrides({"insert": {"confirmation_timeout_s": 0.75}})
            self.assertEqual(
                store.load()["insert"]["confirmation_timeout_s"], 0.75
            )
            with self.assertRaisesRegex(
                SettingsError, "insert.confirmation_timeout_s"
            ):
                store.save_overrides(
                    {"insert": {"confirmation_timeout_s": -0.01}}
                )

    def test_legacy_settle_delay_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            settings = store.load()
            settings["insert"].pop("confirmation_timeout_s")
            settings["insert"]["settle_delay_s"] = 0.15
            SettingsStore.validate(settings)
            store.save_overrides({"insert": {"settle_delay_s": 0.2}})
            loaded = store.load()
            self.assertEqual(loaded["insert"]["settle_delay_s"], 0.2)
            self.assertNotIn("confirmation_timeout_s", loaded["insert"])

    def test_unknown_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(temp)
            store.paths.ensure()
            store.paths.settings.write_text('{"schema_version": 999}')
            with self.assertRaisesRegex(SettingsError, "unsupported settings schema"):
                store.load()


if __name__ == "__main__":
    unittest.main()
