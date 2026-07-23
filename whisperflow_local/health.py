"""Typed product readiness for tray, onboarding, doctor, and diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model_manager import ModelHealth, ModelState
from .platform.macos.permissions import PermissionReport, PermissionStatus


class ProductState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class BackendHealth:
    available: bool
    preferred: bool = True
    detail: str = ""


@dataclass(frozen=True)
class ProductHealth:
    state: ProductState
    detail: str


def assess_product_health(
    permissions: PermissionReport,
    model: ModelHealth,
    cleanup: BackendHealth,
) -> ProductHealth:
    missing_permissions = []
    if permissions.microphone is not PermissionStatus.AUTHORIZED:
        missing_permissions.append("microphone")
    if permissions.accessibility is not PermissionStatus.AUTHORIZED:
        missing_permissions.append("accessibility")
    if missing_permissions:
        return ProductHealth(
            ProductState.BLOCKED,
            "permission required: " + ", ".join(missing_permissions),
        )
    if model.state is ModelState.ERROR:
        return ProductHealth(ProductState.ERROR, model.detail)
    if model.state is not ModelState.READY:
        return ProductHealth(ProductState.BLOCKED, model.detail)
    if not cleanup.available:
        return ProductHealth(ProductState.BLOCKED, cleanup.detail)
    if not cleanup.preferred:
        return ProductHealth(ProductState.DEGRADED, cleanup.detail)
    return ProductHealth(ProductState.READY, "local models and permissions ready")
