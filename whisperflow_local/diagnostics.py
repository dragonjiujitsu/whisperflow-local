"""Redacted local diagnostics safe to copy into a support request."""
from __future__ import annotations

import json
import platform
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from .model_manager import ModelHealth
from .paths import AppPaths, BUNDLE_ID
from .platform.macos.permissions import PermissionReport


def build_diagnostics(
    permissions: PermissionReport,
    model: ModelHealth,
    service_state: str,
    paths: AppPaths | None = None,
) -> dict[str, object]:
    paths = paths or AppPaths.discover()
    return {
        "schema": 1,
        "bundle_id": BUNDLE_ID,
        "macos": platform.mac_ver()[0],
        "machine": platform.machine(),
        "python": platform.python_version(),
        "permissions": {
            "microphone": permissions.microphone.value,
            "accessibility": permissions.accessibility.value,
        },
        "model": {
            "state": model.state.value,
            "installed": model.path is not None,
            "detail": model.detail,
        },
        "service": service_state,
        "settings_present": paths.settings.exists(),
    }


class DiagnosticsWindow(QWidget):
    def __init__(self, report_provider) -> None:
        super().__init__()
        self.report_provider = report_provider
        self.setWindowTitle("WhisperFlow Local Diagnostics")
        self.setMinimumSize(560, 380)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        copy = QPushButton("Copy Redacted Diagnostics")
        copy.clicked.connect(self.copy)
        layout.addWidget(refresh)
        layout.addWidget(copy)
        self.refresh()

    def refresh(self) -> None:
        self.text.setPlainText(
            json.dumps(self.report_provider(), indent=2, sort_keys=True)
        )

    def copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())
