from __future__ import annotations

import unittest
from unittest.mock import patch

from whisperflow_local.platform.macos.accessibility import (
    AccessibilityTarget,
    MacAccessibility,
)


class FakeAPI:
    kAXErrorSuccess = 0
    kAXFocusedApplicationAttribute = "app"
    kAXFocusedUIElementAttribute = "element"
    kAXFocusedWindowAttribute = "window"
    kAXRoleAttribute = "role"
    kAXIdentifierAttribute = "identifier"
    kAXValueAttribute = "value"

    def __init__(self, trusted: bool = True) -> None:
        self.is_trusted = trusted
        self.system = object()
        self.app = object()
        self.element = object()
        self.window = object()
        self.value = "before"

    def AXIsProcessTrusted(self):
        return self.is_trusted

    def AXUIElementCreateSystemWide(self):
        return self.system

    def AXUIElementCopyAttributeValue(self, source, attribute, _):
        values = {
            (self.system, "app"): self.app,
            (self.app, "element"): self.element,
            (self.app, "window"): self.window,
            (self.element, "role"): "AXTextArea",
            (self.element, "identifier"): "composer",
            (self.element, "value"): self.value,
        }
        value = values.get((source, attribute))
        return (0, value) if value is not None else (-1, None)

    def AXUIElementGetPid(self, source, _):
        return (0, 42) if source is self.app else (-1, None)


class FakeCF:
    @staticmethod
    def CFEqual(left, right):
        return left is right


class AccessibilityTests(unittest.TestCase):
    def test_capture_includes_element_window_and_safe_metadata(self) -> None:
        api = FakeAPI()
        target = MacAccessibility(api, FakeCF).capture()
        self.assertEqual(target.pid, 42)
        self.assertEqual(target.role, "AXTextArea")
        self.assertEqual(target.identifier, "composer")
        self.assertTrue(target.native)
        self.assertIs(target.element, api.element)
        self.assertIs(target.window, api.window)

    def test_same_process_different_element_does_not_match(self) -> None:
        api = FakeAPI()
        adapter = MacAccessibility(api, FakeCF)
        target = adapter.capture()
        api.element = object()
        self.assertFalse(adapter.matches(target))

    def test_same_element_different_window_does_not_match(self) -> None:
        api = FakeAPI()
        adapter = MacAccessibility(api, FakeCF)
        target = adapter.capture()
        api.window = object()
        self.assertFalse(adapter.matches(target))

    def test_same_element_and_window_matches(self) -> None:
        api = FakeAPI()
        adapter = MacAccessibility(api, FakeCF)
        target = adapter.capture()
        self.assertTrue(adapter.matches(target))

    def test_untrusted_target_is_not_native(self) -> None:
        api = FakeAPI(trusted=False)
        target = MacAccessibility(api, FakeCF).capture()
        self.assertFalse(target.native)

    @patch(
        "whisperflow_local.platform.macos.accessibility._fallback_frontmost_pid",
        return_value=42,
    )
    def test_untrusted_capture_never_matches_by_pid_alone(self, _fallback) -> None:
        api = FakeAPI(trusted=False)
        adapter = MacAccessibility(api, FakeCF)
        self.assertFalse(adapter.matches(adapter.capture()))

    @patch(
        "whisperflow_local.platform.macos.accessibility._fallback_frontmost_pid",
        return_value=42,
    )
    def test_revoked_accessibility_fails_closed(self, _fallback) -> None:
        api = FakeAPI()
        adapter = MacAccessibility(api, FakeCF)
        target = adapter.capture()
        api.is_trusted = False
        self.assertFalse(adapter.matches(target))

    def test_reads_value_only_from_native_target(self) -> None:
        api = FakeAPI()
        adapter = MacAccessibility(api, FakeCF)
        target = adapter.capture()
        self.assertEqual(adapter.value(target), "before")
        self.assertIsNone(adapter.value(AccessibilityTarget(pid=42)))

    def test_target_does_not_store_field_contents(self) -> None:
        fields = set(AccessibilityTarget.__dataclass_fields__)
        self.assertNotIn("value", fields)
        self.assertNotIn("text", fields)
        self.assertNotIn("contents", fields)


if __name__ == "__main__":
    unittest.main()
