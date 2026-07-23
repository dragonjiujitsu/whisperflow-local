from __future__ import annotations

import unittest
from unittest.mock import patch

from whisperflow_local.platform.macos.permissions import (
    MacPermissions,
    PermissionStatus,
)


class FakeAX:
    kAXTrustedCheckOptionPrompt = "prompt"

    def __init__(self, trusted: bool) -> None:
        self.trusted = trusted
        self.options = None

    def AXIsProcessTrusted(self):
        return self.trusted

    def AXIsProcessTrustedWithOptions(self, options):
        self.options = options
        return self.trusted


class FakeAV:
    AVMediaTypeAudio = "audio"
    AVAuthorizationStatusNotDetermined = 0
    AVAuthorizationStatusRestricted = 1
    AVAuthorizationStatusDenied = 2
    AVAuthorizationStatusAuthorized = 3

    def __init__(self, status: int) -> None:
        self.status = status
        self.requested_media_type = None
        self.request_completion = None

    def AVCaptureDevice(self):
        raise AssertionError("class-style API expected")

    def __getattribute__(self, name):
        if name == "AVCaptureDevice":
            return self
        return object.__getattribute__(self, name)

    def authorizationStatusForMediaType_(self, media_type):
        return self.status

    def requestAccessForMediaType_completionHandler_(self, media_type, completion):
        self.requested_media_type = media_type
        self.request_completion = completion


class PermissionTests(unittest.TestCase):
    def test_ready_requires_both_permissions(self) -> None:
        report = MacPermissions(FakeAX(True), FakeAV(3)).report()
        self.assertTrue(report.ready)
        self.assertEqual(report.microphone, PermissionStatus.AUTHORIZED)
        self.assertEqual(report.accessibility, PermissionStatus.AUTHORIZED)

    def test_denied_accessibility_is_not_ready(self) -> None:
        report = MacPermissions(FakeAX(False), FakeAV(3)).report()
        self.assertFalse(report.ready)
        self.assertEqual(report.accessibility, PermissionStatus.DENIED)

    def test_microphone_states_are_distinct(self) -> None:
        expected = {
            0: PermissionStatus.NOT_DETERMINED,
            1: PermissionStatus.RESTRICTED,
            2: PermissionStatus.DENIED,
            3: PermissionStatus.AUTHORIZED,
            99: PermissionStatus.UNKNOWN,
        }
        for raw, status in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    MacPermissions(FakeAX(True), FakeAV(raw)).microphone_status(),
                    status,
                )

    def test_accessibility_prompt_uses_native_option(self) -> None:
        ax = FakeAX(False)
        MacPermissions(ax, FakeAV(3)).prompt_accessibility()
        self.assertEqual(ax.options, {"prompt": True})

    def test_not_determined_microphone_uses_native_request_api(self) -> None:
        av = FakeAV(0)
        completed = []
        self.assertTrue(
            MacPermissions(FakeAX(True), av).request_microphone(completed.append)
        )
        self.assertEqual(av.requested_media_type, "audio")
        av.request_completion(True)
        self.assertEqual(completed, [True])

    def test_denied_microphone_opens_settings_instead_of_requesting_again(self) -> None:
        av = FakeAV(2)
        permissions = MacPermissions(FakeAX(True), av)
        with patch.object(
            permissions, "open_microphone_settings", return_value=True
        ) as opened:
            self.assertTrue(permissions.request_microphone())
        opened.assert_called_once_with()
        self.assertIsNone(av.requested_media_type)


if __name__ == "__main__":
    unittest.main()
