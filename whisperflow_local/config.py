"""Config loading. Reads config.yaml from the repo root (or a supplied path)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import AppPaths
from .settings import SettingsStore
from .model_manager import ModelManager, ModelState

_BUNDLED_DEFAULTS = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    # convenience accessors -----------------------------------------------
    @property
    def hotkey_combo(self) -> str:
        return self.raw["hotkey"]["combo"]

    @property
    def audio(self) -> dict[str, Any]:
        return self.raw["audio"]

    @property
    def stt(self) -> dict[str, Any]:
        return self.raw["stt"]

    @property
    def cleanup(self) -> dict[str, Any]:
        return self.raw["cleanup"]

    @property
    def insert(self) -> dict[str, Any]:
        return self.raw["insert"]

    @property
    def overlay(self) -> dict[str, Any]:
        return self.raw["overlay"]

    @property
    def sound(self) -> dict[str, Any]:
        return self.raw.get("sound", {"enabled": False})

    @property
    def logging(self) -> dict[str, Any]:
        return self.raw["logging"]

    @property
    def performance(self) -> dict[str, Any]:
        return self.raw.get("performance", {"profile": "instant", "streaming_enabled": False})

    @property
    def personalization(self) -> dict[str, Any]:
        return self.raw.get("personalization", {})

    @property
    def history(self) -> dict[str, Any]:
        return self.raw.get("history", {"enabled": False, "retention_days": 7})

    @property
    def privacy(self) -> dict[str, Any]:
        return self.raw.get("privacy", {"recovery_ttl_seconds": 900})


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        data = SettingsStore(_BUNDLED_DEFAULTS, AppPaths.discover()).load()
        return Config(raw=_resolve_model_paths(data))
    p = Path(path)
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    SettingsStore.validate(data)
    return Config(raw=_resolve_model_paths(data))


def _resolve_model_paths(data: dict[str, Any]) -> dict[str, Any]:
    cleanup = data.get("cleanup")
    if not isinstance(cleanup, dict):
        return data
    health = ModelManager().resolve_gguf(
        repo_id=str(cleanup.get("server_model") or ""),
        variant=str(cleanup.get("server_gguf_variant") or ""),
        configured_path=str(cleanup.get("model_path") or ""),
    )
    if health.state is ModelState.READY and health.path is not None:
        cleanup["model_path"] = str(health.path)
    return data
