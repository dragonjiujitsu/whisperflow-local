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
        confirmation_timeout = cfg.get(
            "confirmation_timeout_s", cfg.get("settle_delay_s", 0.75)
        )
        self._confirmation_timeout = max(
            0.0, float(confirmation_timeout)
        )
        self._confirmation_interval = min(0.025, self._confirmation_timeout)
        self._press_enter = bool(cfg.get("press_enter_after", False))
        self._kb = Controller()
        self._pasteboard = pasteboard or MacPasteboard()
        self._accessibility = accessibility or _ACCESSIBILITY

    def insert(self, text: str, target: FocusTarget) -> tuple[bool, str]:
        """Return whether insertion was safely confirmed.

        A fail-closed paste result may have reached the target even when AX could
        not confirm it, so callers must recover without automatically retrying.
        """
        text = text.strip()
        if not text:
            return False, "empty"
        if not self._accessibility.matches(target):
            return False, "focus_changed"

        ok, reason = (
            self._type(text) if self._mode == "type" else self._paste(text, target)
        )
        if ok and self._press_enter and self._accessibility.matches(target):
            self._kb.tap(Key.enter)
        return ok, reason

    def _type(self, text: str) -> tuple[bool, str]:
        self._kb.type(text)
        return True, "typed"

    def _paste(
        self, text: str, target: FocusTarget | None = None
    ) -> tuple[bool, str]:
        try:
            saved = self._pasteboard.snapshot()
            expected_change = self._pasteboard.write_text(text)
        except Exception as exc:
            return False, f"pasteboard_unavailable:{type(exc).__name__}"
        try:
            try:
                before = self._accessibility.value(target)
                self._kb.press(Key.cmd)
                self._kb.press("v")
                self._kb.release("v")
                self._kb.release(Key.cmd)
            except Exception as exc:
                return False, f"paste_dispatch_failed:{type(exc).__name__}"

            confirmed, reason = self._wait_for_consumption(target, before)
            return (True, "pasted") if confirmed else (False, reason)
        finally:
            # Restore only while our own pasteboard change is still current.
            # The controller owns recovery for any fail-closed result.
            try:
                self._pasteboard.restore_if_unchanged(saved, expected_change)
            except Exception:
                pass

    def _wait_for_consumption(
        self, target: FocusTarget | None, before: str | None
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + self._confirmation_timeout
        while True:
            if target is not None and not self._accessibility.matches(target):
                return False, "focus_changed_during_paste"
            current = self._accessibility.value(target)
            if current is not None and (before is None or current != before):
                return True, "pasted"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, "paste_unconfirmed"
            time.sleep(min(self._confirmation_interval, remaining))
