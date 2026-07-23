from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryItem:
    item_id: str
    text: str
    reason: str
    expires_at: float


class RecoveryStore:
    """Memory-only result recovery; intentionally disappears when the app exits."""

    def __init__(self, ttl_seconds: int = 900, clock=time.time) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._items: dict[str, RecoveryItem] = {}

    def add(self, text: str, reason: str) -> RecoveryItem:
        self.purge()
        item = RecoveryItem(uuid.uuid4().hex, text, reason, self.clock() + self.ttl_seconds)
        self._items[item.item_id] = item
        return item

    def list(self) -> tuple[RecoveryItem, ...]:
        self.purge()
        return tuple(sorted(self._items.values(), key=lambda item: item.expires_at, reverse=True))

    def delete(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    def delete_all(self) -> None:
        self._items.clear()

    def purge(self) -> None:
        now = self.clock()
        self._items = {key: item for key, item in self._items.items() if item.expires_at > now}
