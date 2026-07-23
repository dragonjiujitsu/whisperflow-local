from __future__ import annotations

import tempfile
from pathlib import Path

from whisperflow_local.history import HistoryStore
from whisperflow_local.recovery import RecoveryStore

SENTINEL = "PRIVATE_TRANSCRIPT_SENTINEL_6f213"


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        history_path = root / "history.json"
        history = HistoryStore(history_path, enabled=False)
        recovery = RecoveryStore()
        history.add(SENTINEL)
        recovery.add(SENTINEL, "test")
        if history_path.exists():
            print("FAIL disabled history created a persistence file")
            return 1
        leaked = []
        for path in root.rglob("*"):
            if path.is_file() and SENTINEL.encode() in path.read_bytes(): leaked.append(str(path))
        if leaked:
            print("FAIL transcript sentinel persisted: " + ", ".join(leaked))
            return 1
    print("PASS disabled history and ephemeral recovery persisted no transcript content")
    return 0


if __name__ == "__main__": raise SystemExit(main())
