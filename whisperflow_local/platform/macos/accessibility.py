"""Focused macOS Accessibility element capture and revalidation."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

import ApplicationServices as AS
import CoreFoundation


@dataclass(frozen=True)
class AccessibilityTarget:
    pid: int | None
    bundle_id: str = ""
    role: str = ""
    identifier: str = ""
    native: bool = False
    element: Any = field(default=None, compare=False, repr=False)
    window: Any = field(default=None, compare=False, repr=False)


class MacAccessibility:
    def __init__(self, api=AS, core_foundation=CoreFoundation) -> None:
        self._api = api
        self._cf = core_foundation

    def trusted(self) -> bool:
        return bool(self._api.AXIsProcessTrusted())

    def capture(self) -> AccessibilityTarget:
        if not self.trusted():
            pid = _fallback_frontmost_pid()
            return AccessibilityTarget(pid=pid, bundle_id=_bundle_identifier(pid))
        system = self._api.AXUIElementCreateSystemWide()
        app = self._copy(system, self._api.kAXFocusedApplicationAttribute)
        if app is None:
            pid = _fallback_frontmost_pid()
            return AccessibilityTarget(pid=pid, bundle_id=_bundle_identifier(pid))
        pid = self._pid(app)
        element = self._copy(app, self._api.kAXFocusedUIElementAttribute)
        window = self._copy(app, self._api.kAXFocusedWindowAttribute)
        if element is None:
            return AccessibilityTarget(pid=pid, bundle_id=_bundle_identifier(pid))
        return AccessibilityTarget(
            pid=pid,
            bundle_id=_bundle_identifier(pid),
            role=str(self._copy(element, self._api.kAXRoleAttribute) or ""),
            identifier=str(
                self._copy(element, self._api.kAXIdentifierAttribute) or ""
            ),
            native=True,
            element=element,
            window=window,
        )

    def matches(self, target: AccessibilityTarget) -> bool:
        current = self.capture()
        if target.pid is None or current.pid != target.pid:
            return False
        if not target.native or not current.native:
            return False
        if not self._equal(target.element, current.element):
            return False
        if target.window is not None or current.window is not None:
            return self._equal(target.window, current.window)
        return True

    def value(self, target: AccessibilityTarget) -> str | None:
        """Read a focused field value transiently for paste confirmation."""
        if not target.native or target.element is None or not self.trusted():
            return None
        value = self._copy(target.element, self._api.kAXValueAttribute)
        return value if isinstance(value, str) else None

    def _copy(self, element, attribute):
        try:
            error, value = self._api.AXUIElementCopyAttributeValue(
                element, attribute, None
            )
        except Exception:
            return None
        return value if error == self._api.kAXErrorSuccess else None

    def _pid(self, element) -> int | None:
        try:
            error, value = self._api.AXUIElementGetPid(element, None)
        except Exception:
            return None
        return int(value) if error == self._api.kAXErrorSuccess else None

    def _equal(self, left, right) -> bool:
        if left is None or right is None:
            return left is right
        try:
            return bool(self._cf.CFEqual(left, right))
        except Exception:
            return left == right


def _fallback_frontmost_pid() -> int | None:
    script = (
        'tell application "System Events" to get unix id of first process '
        "whose frontmost is true"
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script], check=True, capture_output=True,
            text=True, timeout=1.0,
        )
        return int(proc.stdout.strip())
    except Exception:
        return None


def _bundle_identifier(pid: int | None) -> str:
    if pid is None:
        return ""
    try:
        import AppKit

        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return str(app.bundleIdentifier() or "") if app is not None else ""
    except Exception:
        return ""
