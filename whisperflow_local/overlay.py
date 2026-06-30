"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

Qt window flags/attributes get the cross-platform 80%; the Win32 extended styles
(WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW) stamped
on the HWND give the hard guarantees.

Visuals: a segmented LED equalizer — tall RGB bars that track live mic RMS — over
a glassy translucent body, with a flowing hue-shift and a subtle animated rainbow
border (rotating conical gradient). Eased attack/decay + idle shimmer.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QRectF, Qt, QTimer, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

# --- Win32 extended-style constants ------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080


def _apply_passthrough_styles(hwnd: int) -> None:
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """Segmented RGB LED equalizer pill. ``set_level(rms)`` (0..1) drives it;
    never steals focus."""

    N_BARS = 21
    SEG_H = 7.0     # LED segment height
    SEG_GAP = 3.0   # gap between segments

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(380, 132)

        self._level = 0.0
        self._smooth = 0.0
        self._t = 0.0
        self._hue = 0.0
        self._bars = [0.0] * self.N_BARS

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
        self._hue = (self._hue + 1.4) % 360

        if self._level > self._smooth:
            self._smooth += (self._level - self._smooth) * 0.5
        else:
            self._smooth += (self._level - self._smooth) * 0.12

        n = self.N_BARS
        for i in range(n):
            pos = i / (n - 1)
            dome = math.sin(math.pi * pos) ** 0.7
            ripple = (
                0.6 * math.sin(self._t * 9 - i * 0.6)
                + 0.4 * math.sin(self._t * 5 + i * 0.35)
            )
            ripple = (ripple + 1) / 2
            idle = 0.12 + 0.07 * math.sin(self._t * 3 + i * 0.5)
            target = idle + dome * (0.30 + 0.70 * ripple) * self._smooth
            self._bars[i] += (max(0.06, min(1.0, target)) - self._bars[i]) * 0.45
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = 8.0
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        radius = 26.0

        # glassy translucent body (NOT pitch black): dark plum -> charcoal
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bg.setColorAt(0.0, QColor(34, 26, 44, 208))
        bg.setColorAt(0.55, QColor(20, 18, 28, 210))
        bg.setColorAt(1.0, QColor(12, 12, 18, 214))
        p.fillPath(body, bg)

        p.setClipPath(body)
        # hue-tinted bottom glow so the body feels alive, not flat black
        glow_col = QColor.fromHsvF(self._hue / 360.0, 0.6, 1.0, 0.10)
        gglow = QLinearGradient(0, rect.bottom(), 0, rect.center().y())
        gglow.setColorAt(0.0, glow_col)
        gglow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(rect, gglow)

        # --- segmented LED bars ---------------------------------------------
        n = self.N_BARS
        usable = rect.width() - 30
        cw = usable / n
        bar_w = min(cw * 0.6, 12.0)
        x0 = rect.left() + 15
        baseline = rect.bottom() - 13
        top_limit = rect.top() + 14
        max_h = baseline - top_limit
        unit = self.SEG_H + self.SEG_GAP
        total_segs = max(3, int(max_h / unit))

        for i in range(n):
            lit = max(1, int(round(self._bars[i] * total_segs)))
            cx = x0 + i * cw + (cw - bar_w) / 2
            for s in range(lit):
                y = baseline - (s + 1) * unit + self.SEG_GAP
                # hue flows across columns AND up each bar; top segments hotter
                hue = (self._hue + i * 10 + s * 4) % 360
                val = 0.75 + 0.25 * (s / total_segs)
                seg = QRectF(cx, y, bar_w, self.SEG_H)
                # glow underlay
                p.fillRect(
                    QRectF(cx - 1.5, y - 1.5, bar_w + 3, self.SEG_H + 3),
                    QColor.fromHsvF(hue / 360.0, 0.85, 1.0, 0.22),
                )
                path = QPainterPath()
                path.addRoundedRect(seg, 2.5, 2.5)
                p.fillPath(path, QColor.fromHsvF(hue / 360.0, 0.78, val, 0.97))
        p.setClipping(False)

        # --- subtle animated rainbow border ---------------------------------
        cg = QConicalGradient(w / 2, h / 2, -self._t * 55 % 360)
        for k in range(7):
            hue = (self._hue + k * 60) % 360
            cg.setColorAt(k / 6.0, QColor.fromHsvF(hue / 360.0, 0.85, 1.0, 0.7))
        pen = QPen(QBrush(cg), 1.8)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)

        # glassy top highlight
        p.setClipPath(body)
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 2),
                   QColor(255, 255, 255, 22))
        p.setClipping(False)
        p.end()
