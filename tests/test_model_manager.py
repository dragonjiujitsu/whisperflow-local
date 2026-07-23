from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local.model_manager import ModelManager, ModelState
from whisperflow_local.paths import AppPaths


class ModelManagerTests(unittest.TestCase):
    def make_manager(self, root: Path) -> ModelManager:
        return ModelManager(
            AppPaths.discover(root / "home"), hf_home=root / "hf"
        )

    def test_valid_configured_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            configured = root / "configured.gguf"
            configured.write_bytes(b"model")
            health = self.make_manager(root).resolve_gguf(
                "org/model", "Q4_K", str(configured)
            )
            self.assertEqual(health.state, ModelState.READY)
            self.assertEqual(health.path, configured)

    def test_stale_snapshot_path_resolves_by_repo_and_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = (
                root / "hf" / "hub" / "models--unsloth--Qwen" /
                "snapshots" / "new-hash" / "Qwen-Q4_K_XL.gguf"
            )
            model.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            health = self.make_manager(root).resolve_gguf(
                "unsloth/Qwen", "Q4_K_XL", "/gone/old-hash/model.gguf"
            )
            self.assertEqual(health.state, ModelState.READY)
            self.assertEqual(health.path, model)
            self.assertEqual(health.detail, "resolved by model identity")

    def test_app_managed_model_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = self.make_manager(root)
            model = manager.paths.models / "Qwen-UD-Q4_K_XL.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            health = manager.resolve_gguf("unsloth/Qwen", "UD-Q4_K_XL")
            self.assertEqual(health.path, model)

    def test_missing_model_has_actionable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            health = self.make_manager(Path(temp)).resolve_gguf(
                "unsloth/Qwen", "Q4_K_XL"
            )
            self.assertEqual(health.state, ModelState.MISSING)
            self.assertIn("unsloth/Qwen", health.detail)

    def test_low_disk_is_distinct_from_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = self.make_manager(Path(temp))
            usage = type("Usage", (), {"free": 100})()
            with patch("whisperflow_local.model_manager.shutil.disk_usage", return_value=usage):
                health = manager.disk_health(required_bytes=1000)
            self.assertEqual(health.state, ModelState.LOW_DISK)


if __name__ == "__main__":
    unittest.main()
