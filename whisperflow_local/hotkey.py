"""Native macOS global hotkey registration.

Unlike a Quartz keyboard event tap, ``RegisterEventHotKey`` listens only for the
declared chord and does not require Input Monitoring permission.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Callable


_CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
_EVENT_HOTKEY_PRESSED = 5
_SIGNATURE = int.from_bytes(b"WFLO", "big")

_MODIFIERS = {
    "cmd": 1 << 8,
    "shift": 1 << 9,
    "alt": 1 << 11,
    "option": 1 << 11,
    "ctrl": 1 << 12,
    "control": 1 << 12,
}
_KEY_CODES = {"space": 49}


class HotkeyRegistrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeChord:
    key_code: int
    modifiers: int


def parse_hotkey(combo: str) -> NativeChord:
    parts = [part.strip().lower().strip("<>") for part in combo.split("+")]
    if len(parts) < 2 or any(not part for part in parts):
        raise ValueError(f"invalid hotkey: {combo!r}")
    key = parts[-1]
    if key not in _KEY_CODES:
        raise ValueError(f"unsupported hotkey key: {key!r}")
    modifiers = 0
    for modifier in parts[:-1]:
        try:
            modifiers |= _MODIFIERS[modifier]
        except KeyError as exc:
            raise ValueError(f"unsupported hotkey modifier: {modifier!r}") from exc
    return NativeChord(_KEY_CODES[key], modifiers)


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("event_class", ctypes.c_uint32), ("event_kind", ctypes.c_uint32)]


_EventHandler = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


class CarbonHotkeyBackend:
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise HotkeyRegistrationError("native hotkeys require macOS")
        self._api = ctypes.CDLL(_CARBON)
        self._configure_api()
        self._hotkey_ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._callback = None

    def _configure_api(self) -> None:
        self._api.GetApplicationEventTarget.restype = ctypes.c_void_p
        self._api.InstallEventHandler.argtypes = [
            ctypes.c_void_p, _EventHandler, ctypes.c_uint32,
            ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._api.InstallEventHandler.restype = ctypes.c_int32
        self._api.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
        ]
        self._api.RegisterEventHotKey.restype = ctypes.c_int32
        self._api.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        self._api.UnregisterEventHotKey.restype = ctypes.c_int32
        self._api.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        self._api.RemoveEventHandler.restype = ctypes.c_int32

    def register(self, chord: NativeChord, on_activate: Callable[[], None]) -> None:
        if self._hotkey_ref.value:
            raise HotkeyRegistrationError("hotkey is already registered")

        @_EventHandler
        def handle_event(_next_handler, _event, _user_data) -> int:
            on_activate()
            return 0

        self._callback = handle_event
        target = self._api.GetApplicationEventTarget()
        event = _EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED)
        status = self._api.InstallEventHandler(
            target, self._callback, 1, ctypes.byref(event), None,
            ctypes.byref(self._handler_ref),
        )
        if status != 0:
            self._callback = None
            raise HotkeyRegistrationError(f"event handler registration failed: {status}")

        status = self._api.RegisterEventHotKey(
            chord.key_code, chord.modifiers,
            _EventHotKeyID(_SIGNATURE, 1), target, 0,
            ctypes.byref(self._hotkey_ref),
        )
        if status != 0:
            self._api.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
            self._callback = None
            raise HotkeyRegistrationError(f"hotkey registration failed: {status}")

    def unregister(self) -> None:
        if self._hotkey_ref.value:
            self._api.UnregisterEventHotKey(self._hotkey_ref)
            self._hotkey_ref = ctypes.c_void_p()
        if self._handler_ref.value:
            self._api.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
        self._callback = None


class HotkeyListener:
    def __init__(
        self, combo: str, on_activate: Callable[[], None], backend=None
    ) -> None:
        self._chord = parse_hotkey(combo)
        self._on_activate = on_activate
        self._backend = backend or CarbonHotkeyBackend()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._backend.register(self._chord, self._on_activate)
        self._started = True

    def stop(self) -> None:
        if self._started:
            self._backend.unregister()
            self._started = False
