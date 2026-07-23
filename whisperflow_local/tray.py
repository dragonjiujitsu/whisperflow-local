"""System-tray presence + clean quit.

An always-on dictation tool needs to be visibly alive and stoppable without
Activity Monitor. This adds a tray icon (painted in-process, no asset file) with a
status line and a Quit action. The caller must keep the returned object alive —
a dropped reference gets garbage-collected and the icon vanishes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

_ICON_FILE = Path(__file__).resolve().parents[1] / "assets" / "icon.png"


def _make_icon() -> QIcon:
    """The sand-pill icon (assets/icon.png). Falls back to a painted mic-dot glyph if the asset is missing."""
    if _ICON_FILE.exists():
        icon = QIcon(str(_ICON_FILE))
        if not icon.isNull():
            return icon
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(34, 34, 40))
    p.drawEllipse(8, 8, 48, 48)
    p.setBrush(QColor(236, 230, 219))
    p.drawRoundedRect(26, 18, 12, 22, 6, 6)  # mic capsule
    p.setPen(QColor(236, 230, 219))
    p.drawLine(32, 40, 32, 48)               # stem
    p.end()
    return QIcon(pix)


def make_tray(
    combo: str,
    on_quit: Callable[[], None],
    on_settings: Callable[[], None] | None = None,
    on_diagnostics: Callable[[], None] | None = None,
    on_recovery: Callable[[], None] | None = None,
) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_make_icon())
    tray.setToolTip(f"whisperflow-local — toggle: {combo}")

    menu = QMenu()
    header = QAction(f"whisperflow-local  ·  {combo}", menu)
    header.setEnabled(False)
    menu.addAction(header)
    status = QAction("Warming local models…", menu)
    status.setEnabled(False)
    menu.addAction(status)
    menu.addSeparator()
    if on_settings is not None:
        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(on_settings)
        menu.addAction(settings_action)
    if on_diagnostics is not None:
        diagnostics_action = QAction("Diagnostics…", menu)
        diagnostics_action.triggered.connect(on_diagnostics)
        menu.addAction(diagnostics_action)
    if on_recovery is not None:
        recovery_action = QAction("Recovery…", menu)
        recovery_action.triggered.connect(on_recovery)
        menu.addAction(recovery_action)
    if on_settings is not None or on_diagnostics is not None or on_recovery is not None:
        menu.addSeparator()
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(on_quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray._status_action = status  # type: ignore[attr-defined]
    tray.show()
    tray.showMessage(
        "whisperflow-local",
        f"Running. Toggle dictation with {combo}.",
        QSystemTrayIcon.Information,
        2500,
    )
    return tray


def update_tray_status(
    tray: QSystemTrayIcon, state: str, detail: str = ""
) -> None:
    action = getattr(tray, "_status_action", None)
    if action is not None:
        label = state.capitalize()
        action.setText(f"{label} · {detail}" if detail else label)
    tray.setToolTip(
        f"WhisperFlow Local — {state}"
        + (f" — {detail}" if detail else "")
    )
