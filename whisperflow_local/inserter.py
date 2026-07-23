"""Focus-checked text insertion for macOS."""
from __future__ import annotations

import time

from pynput.keyboard import Controller, Key

from .platform.macos.accessibility import AccessibilityTarget, MacAccessibility
from .platform.macos.pasteboard import MacPasteboard, PasteboardBackend

FocusTarget = AccessibilityTarget
_ACCESSIBILITY = MacAccessibility()


def capture_focus_target() -> FocusTarget:
    return _ACCESSIBILITY.capture()


def _focus_matches(target: FocusTarget) -> bool:
    return _ACCESSIBILITY.matches(target)


class Inserter:
    def __init__(
        self, cfg: dict, pasteboard: PasteboardBackend | None = None,
        accessibility: MacAccessibility | None = None,
    ) -> None:
        self._mode = cfg.get("mode", "paste")
        self._settle = float(cfg.get("settle_delay_s", 0.15))
        self._press_enter = bool(cfg.get("press_enter_after", False))
        self._kb = Controller()
        self._pasteboard = pasteboard or MacPasteboard()
        self._accessibility = accessibility or _ACCESSIBILITY

    def insert(self, text: str, target: FocusTarget) -> tuple[bool, str]:
        """Returns (ok, reason). ok=False means nothing was inserted."""
        text = text.strip()
        if not text:
            return False, "empty"
        if not self._accessibility.matches(target):
            return False, "focus_changed"

        ok, reason = self._type(text) if self._mode == "type" else self._paste(text)
        if ok and self._press_enter and self._accessibility.matches(target):
            self._kb.tap(Key.enter)
        return ok, reason

    def _type(self, text: str) -> tuple[bool, str]:
        self._kb.type(text)
        return True, "typed"

    def _paste(self, text: str) -> tuple[bool, str]:
        try:
            saved = self._pasteboard.snapshot()
            expected_change = self._pasteboard.write_text(text)
        except Exception as exc:
            return False, f"pasteboard_unavailable:{type(exc).__name__}"
        try:
            self._kb.press(Key.cmd)
            self._kb.press("v")
            self._kb.release("v")
            self._kb.release(Key.cmd)
            time.sleep(self._settle)
            return True, "pasted"
        finally:
            try:
                self._pasteboard.restore_if_unchanged(saved, expected_change)
            except Exception:
                pass
