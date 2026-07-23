"""First-run permission onboarding for the bundled menu-bar app."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .platform.macos.permissions import MacPermissions, PermissionReport, PermissionStatus


def permission_message(name: str, status: PermissionStatus) -> str:
    labels = {
        PermissionStatus.AUTHORIZED: "Ready",
        PermissionStatus.NOT_DETERMINED: "Permission not requested yet",
        PermissionStatus.DENIED: "Permission denied",
        PermissionStatus.RESTRICTED: "Restricted by macOS policy",
        PermissionStatus.UNKNOWN: "Status unavailable",
    }
    return f"{name}: {labels[status]}"


def status_card_style(status: PermissionStatus) -> str:
    if status is PermissionStatus.AUTHORIZED:
        background, foreground, border = "#DDF4E4", "#123B22", "#A8D8B6"
    elif status in {PermissionStatus.DENIED, PermissionStatus.RESTRICTED}:
        background, foreground, border = "#FFE4E1", "#5C1712", "#E6AAA4"
    else:
        background, foreground, border = "#FFF0DF", "#4B2A0B", "#E8C89F"
    return (
        "padding: 7px 10px; border-radius: 6px; "
        f"color: {foreground}; background-color: {background}; "
        f"border: 1px solid {border};"
    )


def python_completion_handler(emit):
    """Wrap a Qt builtin method in a PyObjC-compatible Python block."""
    def completed(granted) -> None:
        emit(bool(granted))

    return completed


def permission_button_state(name: str, status: PermissionStatus) -> tuple[str, bool]:
    if status is PermissionStatus.AUTHORIZED:
        return f"{name} Ready", False
    if status is PermissionStatus.NOT_DETERMINED:
        return f"Request {name}", True
    return f"Open {name} Settings", True


class OnboardingWindow(QWidget):
    microphone_result = Signal(bool)

    def __init__(self, permissions: MacPermissions | None = None) -> None:
        super().__init__()
        self.permissions = permissions or MacPermissions()
        self.setWindowTitle("Welcome to WhisperFlow Local")
        self.setMinimumSize(560, 300)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Private dictation, entirely on this Mac")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        copy = QLabel(
            "WhisperFlow Local needs Microphone access to hear dictation and "
            "Accessibility access to detect the intended field and paste safely. "
            "Audio and cleanup stay local."
        )
        copy.setWordWrap(True)
        layout.addWidget(copy)

        permission_title = QLabel("Permissions")
        permission_title.setStyleSheet("font-size: 14px; font-weight: 600; margin-top: 6px;")
        layout.addWidget(permission_title)

        self.microphone_status = QLabel()
        self.accessibility_status = QLabel()
        layout.addWidget(self.microphone_status)
        layout.addWidget(self.accessibility_status)

        layout.addStretch()

        buttons = QHBoxLayout()
        self.microphone_button = QPushButton("Request Microphone")
        self.microphone_button.clicked.connect(self._request_microphone)
        self.accessibility_button = QPushButton("Request Accessibility")
        self.accessibility_button.clicked.connect(self._request_accessibility)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(self.microphone_button)
        buttons.addWidget(self.accessibility_button)
        buttons.addWidget(refresh)
        layout.addLayout(buttons)
        self.microphone_result.connect(lambda granted: self.refresh())
        # PyObjC cannot turn SignalInstance.emit directly into an Objective-C
        # block. Keep this plain Python closure alive for the async callback.
        self._microphone_completion = python_completion_handler(
            self.microphone_result.emit
        )
        self._permission_refresh_timer = QTimer(self)
        self._permission_refresh_timer.setInterval(1000)
        self._permission_refresh_timer.timeout.connect(self.refresh)
        self._permission_refresh_timer.start()
        self.refresh()

    def _request_microphone(self) -> None:
        if not self.permissions.request_microphone(self._microphone_completion):
            self.microphone_status.setText(
                "Microphone: Could not start the permission request"
            )

    def _request_accessibility(self) -> None:
        self.permissions.prompt_accessibility()
        self.refresh()

    def refresh(self) -> PermissionReport:
        report = self.permissions.report()
        self.microphone_status.setText(
            permission_message("Microphone", report.microphone)
        )
        self.accessibility_status.setText(
            permission_message("Accessibility", report.accessibility)
        )
        for label, status in (
            (self.microphone_status, report.microphone),
            (self.accessibility_status, report.accessibility),
        ):
            label.setStyleSheet(status_card_style(status))
        microphone_text, microphone_enabled = permission_button_state(
            "Microphone", report.microphone
        )
        self.microphone_button.setText(microphone_text)
        self.microphone_button.setEnabled(microphone_enabled)
        accessibility_text, accessibility_enabled = permission_button_state(
            "Accessibility", report.accessibility
        )
        self.accessibility_button.setText(accessibility_text)
        self.accessibility_button.setEnabled(accessibility_enabled)
        return report
