"""Native macOS pasteboard transactions with multi-format preservation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import AppKit


@dataclass(frozen=True)
class PasteboardItem:
    values: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class PasteboardSnapshot:
    items: tuple[PasteboardItem, ...]
    change_count: int


class PasteboardBackend(Protocol):
    def snapshot(self) -> PasteboardSnapshot: ...
    def write_text(self, text: str) -> int: ...
    def restore_if_unchanged(
        self, snapshot: PasteboardSnapshot, expected_change_count: int
    ) -> bool: ...


class MacPasteboard:
    def __init__(self, pasteboard=None) -> None:
        self._pasteboard = pasteboard or AppKit.NSPasteboard.generalPasteboard()

    @property
    def change_count(self) -> int:
        return int(self._pasteboard.changeCount())

    def snapshot(self) -> PasteboardSnapshot:
        items: list[PasteboardItem] = []
        for source in self._pasteboard.pasteboardItems() or ():
            values: list[tuple[str, bytes]] = []
            for type_name in source.types() or ():
                data = source.dataForType_(type_name)
                if data is not None:
                    values.append((str(type_name), bytes(data)))
            items.append(PasteboardItem(tuple(values)))
        return PasteboardSnapshot(tuple(items), self.change_count)

    def write_text(self, text: str) -> int:
        self._pasteboard.clearContents()
        if not self._pasteboard.setString_forType_(
            text, AppKit.NSPasteboardTypeString
        ):
            raise RuntimeError("could not write text to pasteboard")
        return self.change_count

    def restore_if_unchanged(
        self, snapshot: PasteboardSnapshot, expected_change_count: int
    ) -> bool:
        # Never overwrite a clipboard change made by the user or another app
        # while the synthetic paste was settling.
        if self.change_count != expected_change_count:
            return False
        restored = []
        for saved in snapshot.items:
            item = AppKit.NSPasteboardItem.alloc().init()
            for type_name, raw in saved.values:
                data = AppKit.NSData.dataWithBytes_length_(raw, len(raw))
                item.setData_forType_(data, type_name)
            restored.append(item)
        self._pasteboard.clearContents()
        if restored and not self._pasteboard.writeObjects_(restored):
            raise RuntimeError("could not restore pasteboard")
        return True
