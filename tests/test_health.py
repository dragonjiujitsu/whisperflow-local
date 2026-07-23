from __future__ import annotations

import unittest

from whisperflow_local.health import (
    BackendHealth,
    ProductState,
    assess_product_health,
)
from whisperflow_local.model_manager import ModelHealth, ModelState
from whisperflow_local.platform.macos.permissions import (
    PermissionReport,
    PermissionStatus,
)


READY_PERMISSIONS = PermissionReport(
    PermissionStatus.AUTHORIZED, PermissionStatus.AUTHORIZED
)
READY_MODEL = ModelHealth(ModelState.READY)


class ProductHealthTests(unittest.TestCase):
    def test_ready_requires_permissions_model_and_preferred_cleanup(self) -> None:
        health = assess_product_health(
            READY_PERMISSIONS, READY_MODEL, BackendHealth(True, True)
        )
        self.assertEqual(health.state, ProductState.READY)

    def test_missing_permission_blocks_before_backend_health(self) -> None:
        permissions = PermissionReport(
            PermissionStatus.DENIED, PermissionStatus.AUTHORIZED
        )
        health = assess_product_health(
            permissions, READY_MODEL, BackendHealth(True, True)
        )
        self.assertEqual(health.state, ProductState.BLOCKED)
        self.assertIn("microphone", health.detail)

    def test_fallback_cleanup_is_degraded_not_blocked(self) -> None:
        health = assess_product_health(
            READY_PERMISSIONS,
            READY_MODEL,
            BackendHealth(True, False, "direct CLI fallback"),
        )
        self.assertEqual(health.state, ProductState.DEGRADED)
        self.assertEqual(health.detail, "direct CLI fallback")

    def test_missing_model_blocks(self) -> None:
        health = assess_product_health(
            READY_PERMISSIONS,
            ModelHealth(ModelState.MISSING, detail="model missing"),
            BackendHealth(True),
        )
        self.assertEqual(health.state, ProductState.BLOCKED)
        self.assertEqual(health.detail, "model missing")

    def test_backend_unavailable_blocks(self) -> None:
        health = assess_product_health(
            READY_PERMISSIONS,
            READY_MODEL,
            BackendHealth(False, detail="no local cleanup backend"),
        )
        self.assertEqual(health.state, ProductState.BLOCKED)


if __name__ == "__main__":
    unittest.main()
