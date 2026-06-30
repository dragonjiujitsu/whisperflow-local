"""Focus-safe text insertion into the active field (Windows).

Contract (PLAN.md step 5):
  - Capture the focused control at STOP time; re-verify it still has focus
    before inserting, else abort (don't leak text into the wrong field).
  - If the clipboard holds non-text/rich content, use the type() fallback
    instead of clobbering it.
  - Otherwise: save clipboard text -> set cleaned text -> Ctrl+V -> restore.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

import pyperclip
import win32clipboard
import win32con
from pynput.keyboard import Controller, Key

_user32 = ctypes.windll.user32


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


@dataclass(frozen=True)
class FocusTarget:
    foreground: int
    focus: int


def capture_focus_target() -> FocusTarget:
    """Snapshot the foreground window AND the focused control within it."""
    fg = _user32.GetForegroundWindow()
    focus_hwnd = 0
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    tid = _user32.GetWindowThreadProcessId(fg, None)
    if _user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        focus_hwnd = info.hwndFocus or info.hwndActive or fg
    return FocusTarget(foreground=int(fg), focus=int(focus_hwnd))


def _focus_matches(target: FocusTarget) -> bool:
    now = capture_focus_target()
    if now.foreground != target.foreground:
        return False
    # control-level: if we captured a specific focus hwnd, require it to match
    if target.focus and now.focus and now.focus != target.focus:
        return False
    return True


def _clipboard_has_nontext() -> bool:
    """True if the clipboard holds formats other than plain/unicode text."""
    try:
        win32clipboard.OpenClipboard()
        try:
            fmt = win32clipboard.EnumClipboardFormats(0)
            text_formats = {win32con.CF_TEXT, win32con.CF_UNICODETEXT,
                            win32con.CF_OEMTEXT, win32con.CF_LOCALE}
            has_text = False
            has_other = False
            while fmt:
                if fmt in text_formats:
                    has_text = True
                else:
                    has_other = True
                fmt = win32clipboard.EnumClipboardFormats(fmt)
            # rich/binary content present that we can't preserve -> avoid paste
            return has_other and not has_text or (has_other and has_text is False)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


class Inserter:
    def __init__(self, cfg: dict) -> None:
        self._mode = cfg.get("mode", "paste")
        self._settle = float(cfg.get("settle_delay_s", 0.15))
        self._kb = Controller()

    def insert(self, text: str, target: FocusTarget) -> tuple[bool, str]:
        """Returns (ok, reason). ok=False means nothing was inserted."""
        text = text.strip()
        if not text:
            return False, "empty"
        if not _focus_matches(target):
            return False, "focus_changed"

        if self._mode == "type" or _clipboard_has_nontext():
            return self._type(text)
        return self._paste(text)

    # -- strategies -----------------------------------------------------------
    def _type(self, text: str) -> tuple[bool, str]:
        self._kb.type(text)
        return True, "typed"

    def _paste(self, text: str) -> tuple[bool, str]:
        try:
            saved = pyperclip.paste()
        except Exception:
            saved = ""
        try:
            pyperclip.copy(text)
            self._kb.press(Key.ctrl)
            self._kb.press("v")
            self._kb.release("v")
            self._kb.release(Key.ctrl)
            time.sleep(self._settle)
            return True, "pasted"
        finally:
            try:
                pyperclip.copy(saved)
            except Exception:
                pass
