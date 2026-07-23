from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local.applog import get_logger
from whisperflow_local.cleanup import Cleaner
from whisperflow_local.config import load_config
from whisperflow_local.paths import AppPaths

ROOT = Path(__file__).resolve().parents[1]


class ConfigLifecycleTests(unittest.TestCase):
    def test_default_config_layers_application_support_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp))
            paths.ensure()
            paths.settings.write_text(
                '{"schema_version": 1, "audio": {"max_seconds": 77}}'
            )
            with patch(
                "whisperflow_local.config.AppPaths.discover", return_value=paths
            ):
                config = load_config()
            self.assertEqual(config.audio["max_seconds"], 77)
            self.assertEqual(config.audio["sample_rate"], 16000)

    def test_explicit_config_path_remains_supported(self) -> None:
        config = load_config(ROOT / "config.yaml")
        self.assertEqual(config.stt["model"], "distil-large-v3")

    def test_cleanup_key_falls_back_to_keychain(self) -> None:
        cleanup = dict(load_config(ROOT / "config.yaml").cleanup)
        cleanup["api_key"] = ""
        cleanup["api_key_env"] = "UNSET_TEST_KEY"
        with patch.dict("os.environ", {}, clear=True), patch(
            "whisperflow_local.keychain.KeychainSecretStore.get",
            return_value="keychain-secret",
        ):
            cleaner = Cleaner(cleanup)
        self.assertEqual(cleaner._openai_api_key, "keychain-secret")

    def test_logs_use_application_logs_not_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp))
            logger = logging.getLogger("whisperflow_local")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
            with patch(
                "whisperflow_local.applog.AppPaths.discover", return_value=paths
            ):
                configured = get_logger()
            filename = Path(configured.handlers[0].baseFilename)
            self.assertEqual(filename.parent, paths.logs)
            self.assertNotIn("Developer/whisperflow-local", str(filename))
            for handler in list(configured.handlers):
                handler.close()
                configured.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
