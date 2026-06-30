"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

Qt window flags/attributes get the cross-platform 80%; the Win32 extended styles
(WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW) stamped
on the HWND give the hard guarantees.

Visuals: a premium flowing waveform — layered sine ribbons that undulate with live
mic RMS over a glassy translucent body, in a restrained cool gradient (no RGB
cycling). Gentle idle motion, eased attack/decay, soft glow, hairline border.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
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

# restrained, premium cool palette (no hue cycling)
C_BLUE = QColor(0x6E, 0xA8, 0xFE)    # soft blue
C_LILAC = QColor(0xB7, 0x9C, 0xF5)   # lavender
C_TEAL = QColor(0x6F, 0xE7, 0xD2)    # soft teal


def _apply_passthrough_styles(hwnd: int) -> None:
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """Premium flowing-waveform pill. ``set_level(rms)`` (0..1) drives the
    amplitude; never steals focus."""

    # three layered ribbons: (freq, speed, amp-scale, alpha)
    LAYERS = (
        (1.4, 1.7, 1.00, 230),
        (2.3, -1.1, 0.62, 150),
        (3.1, 0.8, 0.40, 90),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(360, 104)

        self._level = 0.0
        self._smooth = 0.0
        self._t = 0.0

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
        if self._level > self._smooth:
            self._smooth += (self._level - self._smooth) * 0.45
        else:
            self._smooth += (self._level - self._smooth) * 0.10
        self.update()

    def _wave_path(self, rect: QRectF, freq: float, speed: float,
                   amp: float, phase: float) -> QPainterPath:
        cy = rect.center().y()
        left = rect.left() + 18
        right = rect.right() - 18
        width = right - left
        path = QPainterPath()
        steps = 64
        for k in range(steps + 1):
            fx = k / steps
            x = left + fx * width
            env = math.sin(math.pi * fx)  # taper to 0 at both ends
            y = cy + env * amp * math.sin(2 * math.pi * freq * fx + phase)
            if k == 0:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))
        return path

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        margin = 8.0
        rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        radius = rect.height() / 2

        # glassy translucent body — deep slate, subtly see-through
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bg.setColorAt(0.0, QColor(26, 28, 38, 205))
        bg.setColorAt(1.0, QColor(15, 16, 22, 212))
        p.fillPath(body, bg)

        p.setClipPath(body)

        # amplitude: gentle idle breathing + voice
        max_amp = (rect.height() / 2) - 10
        amp = max_amp * (0.16 + 0.84 * self._smooth)

        # shared horizontal gradient for the ribbons (cool, no cycling)
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad.setColorAt(0.0, C_BLUE)
        grad.setColorAt(0.5, C_LILAC)
        grad.setColorAt(1.0, C_TEAL)

        for freq, speed, ascale, alpha in self.LAYERS:
            path = self._wave_path(rect, freq, speed, amp * ascale, self._t * speed)
            # soft glow pass
            glow = QColor(C_LILAC)
            glow.setAlpha(int(alpha * 0.28))
            p.setPen(QPen(glow, 6.0))
            p.drawPath(path)
            # crisp gradient stroke
            pen = QPen(QBrush(grad), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            # apply layer alpha by drawing into a clipped translucent pass
            p.setOpacity(alpha / 255.0)
            p.setPen(pen)
            p.drawPath(path)
            p.setOpacity(1.0)

        p.setClipping(False)

        # hairline border + glassy top highlight (subtle, static)
        p.setPen(QPen(QColor(255, 255, 255, 36), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.setClipPath(body)
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 1.5),
                   QColor(255, 255, 255, 26))
        p.setClipping(False)
        p.end()
