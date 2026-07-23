from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class HistoryEntry:
    entry_id: str
    created_at: float
    text: str
    app_id: str = ""


class HistoryStore:
    """Opt-in, retention-bounded local history protected by POSIX user-only access."""

    def __init__(self, path: Path, *, enabled: bool = False, retention_days: int = 7) -> None:
        if retention_days < 1 or retention_days > 365:
            raise ValueError("retention_days must be between 1 and 365")
        self.path = path
        self.enabled = enabled
        self.retention_days = retention_days

    def add(self, text: str, app_id: str = "", now: float | None = None) -> HistoryEntry | None:
        if not self.enabled:
            return None
        entry = HistoryEntry(uuid.uuid4().hex, now or time.time(), text, app_id)
        entries = [*self.list(now=entry.created_at), entry]
        self._write(entries)
        return entry

    def list(self, now: float | None = None) -> list[HistoryEntry]:
        if not self.enabled or not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = [HistoryEntry(**item) for item in raw.get("entries", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        cutoff = (now or time.time()) - self.retention_days * 86400
        retained = [entry for entry in entries if entry.created_at >= cutoff]
        if len(retained) != len(entries):
            self._write(retained)
        return retained

    def delete(self, entry_id: str) -> None:
        self._write([entry for entry in self.list() if entry.entry_id != entry_id])

    def delete_all(self) -> None:
        self.path.unlink(missing_ok=True)

    def export_to(self, destination: Path) -> None:
        self._write_private(
            destination,
            json.dumps([asdict(item) for item in self.list()], indent=2) + "\n",
        )

    def _write(self, entries: list[HistoryEntry]) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write_private(
            self.path,
            json.dumps(
                {"schema_version": 1, "entries": [asdict(item) for item in entries]}
            ),
        )

    @staticmethod
    def _write_private(destination: Path, content: str) -> None:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temp = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, destination)
            os.chmod(destination, 0o600)
        finally:
            temp.unlink(missing_ok=True)
