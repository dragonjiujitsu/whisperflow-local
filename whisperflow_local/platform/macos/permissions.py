"""Native macOS privacy permission health and recovery links."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import AVFoundation
import ApplicationServices as AS


class PermissionStatus(str, Enum):
    NOT_DETERMINED = "not_determined"
    DENIED = "denied"
    RESTRICTED = "restricted"
    AUTHORIZED = "authorized"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PermissionReport:
    microphone: PermissionStatus
    accessibility: PermissionStatus

    @property
    def ready(self) -> bool:
        return (
            self.microphone is PermissionStatus.AUTHORIZED
            and self.accessibility is PermissionStatus.AUTHORIZED
        )


class MacPermissions:
    MICROPHONE_SETTINGS = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
    )
    ACCESSIBILITY_SETTINGS = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    )

    def __init__(self, accessibility=AS, avfoundation=AVFoundation) -> None:
        self._ax = accessibility
        self._av = avfoundation

    def report(self) -> PermissionReport:
        return PermissionReport(
            microphone=self.microphone_status(),
            accessibility=(
                PermissionStatus.AUTHORIZED
                if self._ax.AXIsProcessTrusted()
                else PermissionStatus.DENIED
            ),
        )

    def microphone_status(self) -> PermissionStatus:
        raw = self._av.AVCaptureDevice.authorizationStatusForMediaType_(
            self._av.AVMediaTypeAudio
        )
        mapping = {
            self._av.AVAuthorizationStatusNotDetermined:
                PermissionStatus.NOT_DETERMINED,
            self._av.AVAuthorizationStatusRestricted: PermissionStatus.RESTRICTED,
            self._av.AVAuthorizationStatusDenied: PermissionStatus.DENIED,
            self._av.AVAuthorizationStatusAuthorized: PermissionStatus.AUTHORIZED,
        }
        return mapping.get(raw, PermissionStatus.UNKNOWN)

    def prompt_accessibility(self) -> bool:
        options = {self._ax.kAXTrustedCheckOptionPrompt: True}
        return bool(self._ax.AXIsProcessTrustedWithOptions(options))

    def request_microphone(
        self, completion: Callable[[bool], None] | None = None
    ) -> bool:
        """Create the TCC registration before directing the user to Settings."""
        callback = completion or (lambda granted: None)
        status = self.microphone_status()
        if status is PermissionStatus.AUTHORIZED:
            callback(True)
            return True
        if status is PermissionStatus.NOT_DETERMINED:
            try:
                self._av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    self._av.AVMediaTypeAudio, callback
                )
                return True
            except Exception:
                return False
        opened = self.open_microphone_settings()
        callback(False)
        return opened

    def open_microphone_settings(self) -> bool:
        return self._open(self.MICROPHONE_SETTINGS)

    def open_accessibility_settings(self) -> bool:
        return self._open(self.ACCESSIBILITY_SETTINGS)

    @staticmethod
    def _open(url: str) -> bool:
        try:
            return subprocess.run(
                ["open", url], check=False, capture_output=True, timeout=5.0
            ).returncode == 0
        except Exception:
            return False
