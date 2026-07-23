"""Stable macOS application-owned paths independent of repo or bundle cwd."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BUNDLE_ID = "com.shawnvanbrunt.whisperflow-local"
APP_SUPPORT_NAME = "WhisperFlow Local"


@dataclass(frozen=True)
class AppPaths:
    support: Path
    cache: Path
    logs: Path

    @classmethod
    def discover(cls, home: Path | None = None) -> "AppPaths":
        root = (home or Path.home()).expanduser().resolve()
        return cls(
            support=root / "Library" / "Application Support" / APP_SUPPORT_NAME,
            cache=root / "Library" / "Caches" / BUNDLE_ID,
            logs=root / "Library" / "Logs" / APP_SUPPORT_NAME,
        )

    @property
    def settings(self) -> Path:
        return self.support / "settings.json"

    @property
    def models(self) -> Path:
        return self.support / "Models"

    @property
    def recovery(self) -> Path:
        return self.support / "Recovery"

    @property
    def metrics(self) -> Path:
        return self.logs / "metrics.jsonl"

    def ensure(self) -> "AppPaths":
        for directory in (
            self.support, self.cache, self.logs, self.models, self.recovery
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self
