"""Local model discovery and health independent of snapshot hashes."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .paths import AppPaths


class ModelState(str, Enum):
    READY = "ready"
    MISSING = "missing"
    LOW_DISK = "low_disk"
    ERROR = "error"


@dataclass(frozen=True)
class ModelHealth:
    state: ModelState
    path: Path | None = None
    detail: str = ""


class ModelManager:
    def __init__(
        self, paths: AppPaths | None = None, hf_home: Path | None = None
    ) -> None:
        self.paths = paths or AppPaths.discover()
        configured_hf = os.environ.get("HF_HOME")
        self.hf_home = (
            Path(configured_hf).expanduser()
            if configured_hf
            else hf_home or Path.home() / ".cache" / "huggingface"
        )

    def resolve_gguf(
        self, repo_id: str, variant: str = "", configured_path: str = ""
    ) -> ModelHealth:
        if configured_path:
            candidate = Path(configured_path).expanduser()
            if candidate.is_file():
                return ModelHealth(ModelState.READY, candidate, "configured path")

        names = self._name_fragments(variant)
        candidates = list(self._app_candidates(names)) + list(
            self._huggingface_candidates(repo_id, names)
        )
        files = [path for path in candidates if path.is_file()]
        if not files:
            return ModelHealth(
                ModelState.MISSING,
                detail=f"{repo_id} {variant or 'GGUF'} is not installed",
            )
        selected = max(files, key=lambda path: path.stat().st_mtime)
        return ModelHealth(ModelState.READY, selected, "resolved by model identity")

    def disk_health(self, required_bytes: int = 0) -> ModelHealth:
        try:
            self.paths.ensure()
            free = shutil.disk_usage(self.paths.support).free
        except OSError as exc:
            return ModelHealth(ModelState.ERROR, detail=str(exc))
        reserve = max(required_bytes, 2 * 1024**3)
        if free < reserve:
            return ModelHealth(
                ModelState.LOW_DISK,
                detail=f"{free} bytes free; {reserve} required",
            )
        return ModelHealth(ModelState.READY, self.paths.models, f"{free} bytes free")

    def _app_candidates(self, fragments: tuple[str, ...]):
        root = self.paths.models
        if not root.exists():
            return ()
        return (
            path for path in root.rglob("*.gguf")
            if all(fragment in path.name.lower() for fragment in fragments)
        )

    def _huggingface_candidates(
        self, repo_id: str, fragments: tuple[str, ...]
    ):
        repo_dir = "models--" + repo_id.replace("/", "--")
        snapshots = self.hf_home / "hub" / repo_dir / "snapshots"
        if not snapshots.exists():
            return ()
        return (
            path for path in snapshots.glob("*/*.gguf")
            if all(fragment in path.name.lower() for fragment in fragments)
        )

    @staticmethod
    def _name_fragments(variant: str) -> tuple[str, ...]:
        normalized = variant.lower().replace("-", "_")
        return tuple(part for part in normalized.split("_") if part)
