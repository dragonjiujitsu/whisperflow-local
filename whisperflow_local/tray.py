"""System-tray presence + clean quit.

An always-on dictation tool needs to be visibly alive and stoppable without
Task Manager. This adds a tray icon (painted in-process, no asset file) with a
status line and a Quit action. The caller must keep the returned object alive —
a dropped reference gets garbage-collected and the icon vanishes.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    """A small mic-dot glyph, drawn at runtime so we ship no .ico file."""
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


def make_tray(combo: str, on_quit: Callable[[], None]) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_make_icon())
    tray.setToolTip(f"whisperflow-local — toggle: {combo}")

    menu = QMenu()
    header = QAction(f"whisperflow-local  ·  {combo}", menu)
    header.setEnabled(False)
    menu.addAction(header)
    menu.addSeparator()
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(on_quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    tray.showMessage(
        "whisperflow-local",
        f"Running. Toggle dictation with {combo}.",
        QSystemTrayIcon.Information,
        2500,
    )
    return tray
