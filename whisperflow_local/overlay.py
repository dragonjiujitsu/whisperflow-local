"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

We get there with Qt window flags/attributes for the cross-platform 80%, then
stamp the Win32 extended styles (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT |
WS_EX_LAYERED | WS_EX_TOOLWINDOW) directly on the HWND for the hard guarantees.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

# --- Win32 extended-style constants ------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000  # never becomes the active/focused window
WS_EX_TRANSPARENT = 0x00000020  # mouse events fall through to the window behind
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar entry, no alt-tab


def _apply_passthrough_styles(hwnd: int) -> None:
    """Force the no-activate + click-through extended styles onto the HWND."""
    import win32con  # noqa: F401  (kept for readers; constants inlined above)
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """A small rounded pill that animates to live mic amplitude.

    Call ``set_level(rms)`` (0.0..1.0) repeatedly to drive the bars. The widget
    never steals focus, so the caller can safely paste into the active field.
    """

    N_BARS = 5

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # keeps it out of the taskbar / alt-tab
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # show != focus
        self.resize(180, 64)

        self._level = 0.0
        self._bar_phase = [i / self.N_BARS for i in range(self.N_BARS)]

        # smooth idle shimmer so the pill looks alive between RMS updates
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.setInterval(33)  # ~30 fps

    # -- public API -----------------------------------------------------------
    @Slot(float)
    def set_level(self, rms: float) -> None:
        self._level = max(0.0, min(1.0, rms))

    def show_pill(self) -> None:
        self._position_bottom_center()
        self.show()
        # Re-stamp Win32 styles AFTER the native window exists.
        if sys.platform == "win32":
            _apply_passthrough_styles(int(self.winId()))
        self._tick.start()

    def hide_pill(self) -> None:
        self._tick.stop()
        self.hide()

    # -- internals ------------------------------------------------------------
    def _position_bottom_center(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - self.width() // 2
        y = screen.bottom() - self.height() - 80
        self.move(x, y)

    def _animate(self) -> None:
        for i in range(self.N_BARS):
            self._bar_phase[i] = (self._bar_phase[i] + 0.08) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt signature)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # pill background
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(2, 2, -2, -2), 28, 28)
        p.fillPath(path, QColor(20, 20, 24, 220))

        # level bars
        import math

        bar_w = 10
        gap = 8
        total = self.N_BARS * bar_w + (self.N_BARS - 1) * gap
        x0 = (self.width() - total) // 2
        cy = self.height() // 2
        for i in range(self.N_BARS):
            wobble = (math.sin(self._bar_phase[i] * 2 * math.pi) + 1) / 2
            amp = 0.25 + 0.75 * self._level
            h = int(8 + wobble * amp * (self.height() - 24))
            x = x0 + i * (bar_w + gap)
            color = QColor(0xE2, 0x72, 0x4B)  # terracotta
            bar = QPainterPath()
            bar.addRoundedRect(x, cy - h / 2, bar_w, h, 4, 4)
            p.fillPath(bar, color)
        p.end()
