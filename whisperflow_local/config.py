"""Config loading. Reads config.yaml from the repo root (or a supplied path)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


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
    def logging(self) -> dict[str, Any]:
        return self.raw["logging"]


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else _DEFAULT_PATH
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Config(raw=data)
