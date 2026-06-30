"""Global toggle hotkey via pynput.

Default chord is ``<ctrl>+<cmd>`` (Ctrl+Win — Wispr Flow's Windows default; a
modifier pair with no built-in OS action, so no reserved-combo collision). Each
activation invokes the supplied callback; the caller owns the
IDLE/RECORDING/PROCESSING state machine.
"""
from __future__ import annotations

from typing import Callable

from pynput import keyboard


class HotkeyListener:
    def __init__(self, combo: str, on_activate: Callable[[], None]) -> None:
        self._combo = combo
        self._on_activate = on_activate
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        self._listener = keyboard.GlobalHotKeys({self._combo: self._on_activate})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
