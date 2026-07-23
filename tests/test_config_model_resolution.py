from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local.config import _resolve_model_paths
from whisperflow_local.model_manager import ModelHealth, ModelState


class ConfigModelResolutionTests(unittest.TestCase):
    def test_ready_identity_replaces_stale_snapshot_path(self) -> None:
        data = {
            "cleanup": {
                "server_model": "unsloth/model",
                "server_gguf_variant": "Q4_K_XL",
                "model_path": "/stale/hash/model.gguf",
            }
        }
        resolved = Path("/stable/cache/model.gguf")
        with patch(
            "whisperflow_local.config.ModelManager.resolve_gguf",
            return_value=ModelHealth(ModelState.READY, resolved),
        ) as resolve:
            result = _resolve_model_paths(data)
        self.assertEqual(result["cleanup"]["model_path"], str(resolved))
        resolve.assert_called_once_with(
            repo_id="unsloth/model",
            variant="Q4_K_XL",
            configured_path="/stale/hash/model.gguf",
        )

    def test_missing_identity_preserves_config_for_actionable_health(self) -> None:
        data = {
            "cleanup": {
                "server_model": "unsloth/model",
                "server_gguf_variant": "Q4_K_XL",
                "model_path": "/stale/hash/model.gguf",
            }
        }
        with patch(
            "whisperflow_local.config.ModelManager.resolve_gguf",
            return_value=ModelHealth(ModelState.MISSING, detail="missing"),
        ):
            result = _resolve_model_paths(data)
        self.assertEqual(
            result["cleanup"]["model_path"], "/stale/hash/model.gguf"
        )


if __name__ == "__main__":
    unittest.main()
