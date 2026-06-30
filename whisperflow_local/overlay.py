"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

We get there with Qt window flags/attributes for the cross-platform 80%, then
stamp the Win32 extended styles (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT |
WS_EX_LAYERED | WS_EX_TOOLWINDOW) directly on the HWND for the hard guarantees.

Visuals: a glassy rounded pill with a smooth, mirrored audio waveform driven by
live mic RMS — eased attack/decay, a brand gradient (terracotta -> cobalt), soft
glow, and an idle shimmer so it always looks alive.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

# --- Win32 extended-style constants ------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000  # never becomes the active/focused window
WS_EX_TRANSPARENT = 0x00000020  # mouse events fall through to the window behind
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar entry, no alt-tab

# brand palette
TERRACOTTA = QColor(0xE2, 0x72, 0x4B)
CORAL = QColor(0xF2, 0x9A, 0x5C)
COBALT = QColor(0x3B, 0x6B, 0xF0)
VIOLET = QColor(0x8B, 0x5C, 0xF6)


def _apply_passthrough_styles(hwnd: int) -> None:
    """Force the no-activate + click-through extended styles onto the HWND."""
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """A glassy pill with a live, reactive waveform. ``set_level(rms)`` (0..1)
    drives it; never steals focus."""

    N_BARS = 27  # odd -> symmetric center

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(300, 84)

        self._level = 0.0       # raw target from set_level
        self._smooth = 0.0      # eased level (attack/decay)
        self._t = 0.0           # animation clock
        self._bars = [0.0] * self.N_BARS  # current per-bar heights (eased)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.setInterval(16)  # ~60 fps

    # -- public API -----------------------------------------------------------
    @Slot(float)
    def set_level(self, rms: float) -> None:
        self._level = max(0.0, min(1.0, rms))

    def show_pill(self) -> None:
        self._position_bottom_center()
        self.show()
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
        y = screen.bottom() - self.height() - 90
        self.move(x, y)

    def _animate(self) -> None:
        self._t += 0.016
        # eased level: fast attack, slow decay (feels responsive + smooth)
        if self._level > self._smooth:
            self._smooth += (self._level - self._smooth) * 0.5
        else:
            self._smooth += (self._level - self._smooth) * 0.12

        n = self.N_BARS
        for i in range(n):
            # dome envelope so center bars are tallest
            pos = i / (n - 1)
            dome = math.sin(math.pi * pos) ** 0.7
            # two travelling ripples for organic motion
            ripple = (
                0.6 * math.sin(self._t * 9 - i * 0.6)
                + 0.4 * math.sin(self._t * 5 + i * 0.35)
            )
            ripple = (ripple + 1) / 2  # 0..1
            idle = 0.10 + 0.06 * math.sin(self._t * 3 + i * 0.5)
            target = idle + dome * (0.25 + 0.75 * ripple) * self._smooth
            target = max(0.04, min(1.0, target))
            # ease each bar toward its target
            self._bars[i] += (target - self._bars[i]) * 0.45
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt signature)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # soft outer glow (concentric translucent rounded rects)
        for i, a in enumerate((10, 18, 30)):
            inset = 2 + (3 - i) * 3
            glow = QPainterPath()
            glow.addRoundedRect(
                inset, inset, w - 2 * inset, h - 2 * inset, h / 2, h / 2
            )
            col = QColor(TERRACOTTA)
            col.setAlpha(a)
            p.fillPath(glow, col)

        # glassy pill body with subtle vertical gradient
        body = QPainterPath()
        body.addRoundedRect(8, 8, w - 16, h - 16, (h - 16) / 2, (h - 16) / 2)
        bg = QLinearGradient(0, 8, 0, h - 8)
        bg.setColorAt(0.0, QColor(28, 28, 34, 235))
        bg.setColorAt(1.0, QColor(14, 14, 18, 235))
        p.fillPath(body, bg)
        # thin top highlight border
        p.setClipPath(body)
        border = QColor(255, 255, 255, 22)
        p.fillRect(8, 8, w - 16, 2, border)
        p.setClipping(False)

        # waveform bars (mirrored around vertical center)
        n = self.N_BARS
        bar_w = 5.0
        gap = (w - 56 - n * bar_w) / (n - 1)
        x0 = 28.0
        cy = h / 2.0
        max_h = h - 34
        for i in range(n):
            bh = self._bars[i] * max_h
            x = x0 + i * (bar_w + gap)
            top = cy - bh / 2
            # per-bar gradient: warm at top -> cool at bottom, hue shifts across
            t = i / (n - 1)
            grad = QLinearGradient(0, top, 0, top + bh)
            grad.setColorAt(0.0, _mix(CORAL, VIOLET, t))
            grad.setColorAt(1.0, _mix(TERRACOTTA, COBALT, t))

            # glow underlay (wider, low alpha)
            glow_path = QPainterPath()
            glow_path.addRoundedRect(x - 1.5, top - 1.5, bar_w + 3, bh + 3, 4, 4)
            gc = _mix(CORAL, COBALT, t)
            gc.setAlpha(70)
            p.fillPath(glow_path, gc)

            # crisp bar
            bar = QPainterPath()
            bar.addRoundedRect(x, top, bar_w, bh, bar_w / 2, bar_w / 2)
            p.fillPath(bar, grad)
        p.end()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )
