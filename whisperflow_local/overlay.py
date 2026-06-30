"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

Qt window flags/attributes get the cross-platform 80%; the Win32 extended styles
(WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW) stamped
on the HWND give the hard guarantees.

Visuals: a premium flowing waveform — layered sine ribbons in a cool gradient —
over a glassy body with a soft drop shadow (3D float) and an animated film-grain
overlay for texture. No RGB cycling.
"""
from __future__ import annotations

import math
import sys

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
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

# cool palette — a touch more vivid than before, still restrained
C_BLUE = QColor(0x4F, 0x97, 0xFF)
C_LILAC = QColor(0xB4, 0x82, 0xFF)
C_TEAL = QColor(0x3E, 0xE8, 0xCD)


def _apply_passthrough_styles(hwnd: int) -> None:
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """Premium flowing-waveform pill with drop shadow + film grain.
    ``set_level(rms)`` (0..1) drives amplitude; never steals focus."""

    LAYERS = (
        (1.4, 1.7, 1.00, 245),
        (2.3, -1.1, 0.62, 165),
        (3.1, 0.8, 0.40, 100),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(392, 132)

        self._level = 0.0
        self._smooth = 0.0
        self._t = 0.0
        self._grain_idx = 0

        # precompute a handful of film-grain tiles (cycled for animation)
        self._grain_arrs: list[np.ndarray] = []
        self._grain_imgs: list[QImage] = []
        self._build_grain(self.width(), self.height(), tiles=10)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.setInterval(16)  # ~60 fps

    def _build_grain(self, w: int, h: int, tiles: int) -> None:
        for _ in range(tiles):
            arr = np.random.randint(0, 256, (h, w), dtype=np.uint8)
            arr = np.ascontiguousarray(arr)
            img = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
            self._grain_arrs.append(arr)  # keep buffer alive
            self._grain_imgs.append(img)

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
        y = screen.bottom() - self.height() - 86
        self.move(x, y)

    def _animate(self) -> None:
        self._t += 0.016
        if self._level > self._smooth:
            self._smooth += (self._level - self._smooth) * 0.45
        else:
            self._smooth += (self._level - self._smooth) * 0.10
        self._grain_idx = (self._grain_idx + 1) % len(self._grain_imgs)
        self.update()

    def _wave_path(self, rect: QRectF, freq: float, amp: float,
                   phase: float) -> QPainterPath:
        cy = rect.center().y()
        left = rect.left() + 18
        right = rect.right() - 18
        width = right - left
        path = QPainterPath()
        steps = 72
        for k in range(steps + 1):
            fx = k / steps
            x = left + fx * width
            env = math.sin(math.pi * fx)
            y = cy + env * amp * math.sin(2 * math.pi * freq * fx + phase)
            (path.moveTo if k == 0 else path.lineTo)(QPointF(x, y))
        return path

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # leave room for the drop shadow around the body
        rect = QRectF(18, 12, w - 36, h - 34)
        radius = rect.height() / 2

        # --- soft drop shadow (stacked translucent halos, offset down) -------
        for i in range(14, 0, -1):
            sr = QRectF(rect).adjusted(-i, -i, i, i)
            sr.translate(0, 6)
            a = max(0, int(10 - i * 0.7))
            if a <= 0:
                continue
            sp = QPainterPath()
            sp.addRoundedRect(sr, radius + i, radius + i)
            p.fillPath(sp, QColor(0, 0, 0, a))

        # --- glassy body with vertical bevel gradient ------------------------
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bg.setColorAt(0.0, QColor(34, 37, 50, 210))
        bg.setColorAt(0.5, QColor(22, 24, 33, 212))
        bg.setColorAt(1.0, QColor(13, 14, 20, 216))
        p.fillPath(body, bg)

        p.setClipPath(body)

        # waveform amplitude: gentle idle + voice
        max_amp = (rect.height() / 2) - 9
        amp = max_amp * (0.16 + 0.84 * self._smooth)
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad.setColorAt(0.0, C_BLUE)
        grad.setColorAt(0.5, C_LILAC)
        grad.setColorAt(1.0, C_TEAL)

        for freq, _speed, ascale, alpha in self.LAYERS:
            path = self._wave_path(rect, freq, amp * ascale, self._t * _speed)
            glow = QColor(C_LILAC)
            glow.setAlpha(int(alpha * 0.34))
            p.setPen(QPen(glow, 7.0))
            p.drawPath(path)
            pen = QPen(QBrush(grad), 2.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setOpacity(alpha / 255.0)
            p.setPen(pen)
            p.drawPath(path)
            p.setOpacity(1.0)

        # --- film grain (animated, Overlay blend, subtle) --------------------
        p.setOpacity(0.06)
        p.setCompositionMode(QPainter.CompositionMode_Overlay)
        p.drawImage(self.rect(), self._grain_imgs[self._grain_idx])
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setOpacity(1.0)

        # inner bottom shadow for 3D depth
        depth = QLinearGradient(0, rect.bottom() - 14, 0, rect.bottom())
        depth.setColorAt(0.0, QColor(0, 0, 0, 0))
        depth.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.fillRect(rect, depth)
        p.setClipping(False)

        # hairline border + top glass highlight
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.setClipPath(body)
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 1.5),
                   QColor(255, 255, 255, 30))
        p.setClipping(False)
        p.end()
