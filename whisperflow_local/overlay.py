"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

Qt window flags/attributes get the cross-platform 80%; the Win32 extended styles
(WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW) stamped
on the HWND give the hard guarantees.

Visuals: a lo-fi "sand" waveform — thousands of fine ink strands (random length +
opacity) forming a mic-reactive envelope on a soft parchment pill. Strands are
re-scattered each frame so it shimmers like pencil/ink texture.
"""
from __future__ import annotations

import math
import sys

import numpy as np
from PySide6.QtCore import QLineF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

# --- Win32 extended-style constants ------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080

INK = (38, 36, 40)          # charcoal strands
ALPHA_BUCKETS = (34, 64, 104, 158)  # 4 opacity tiers for the strands


def _apply_passthrough_styles(hwnd: int) -> None:
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """Lo-fi sand/ink waveform pill. ``set_level(rms)`` (0..1) drives amplitude;
    never steals focus."""

    COLS = 96

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(400, 150)

        self._level = 0.0
        self._smooth = 0.0
        self._t = 0.0

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.setInterval(33)  # ~30 fps (strand field is heavier)

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
        y = screen.bottom() - self.height() - 80
        self.move(x, y)

    def _animate(self) -> None:
        self._t += 0.033
        if self._level > self._smooth:
            self._smooth += (self._level - self._smooth) * 0.5
        else:
            self._smooth += (self._level - self._smooth) * 0.12
        self.update()

    def _strand_buckets(self, rect: QRectF):
        """Return 4 lists of QLineF (one per opacity tier)."""
        left = rect.left() + 22
        right = rect.right() - 22
        width = right - left
        cy = rect.center().y()
        max_h = rect.height() / 2 - 12
        t = self._t

        fx = np.linspace(0.0, 1.0, self.COLS)
        # moving multi-hump envelope (like a real waveform), tapered at edges
        prof = np.abs(
            0.60 * np.sin(2 * np.pi * 1.3 * fx + t * 1.4)
            + 0.40 * np.sin(2 * np.pi * 2.1 * fx - t * 0.9)
        )
        prof = prof / (prof.max() or 1.0)
        edge = np.sin(np.pi * fx) ** 0.8
        env = (0.18 + 0.82 * self._smooth) * max_h * (0.22 + 0.78 * prof) * edge
        xcol = left + fx * width

        buckets = [[], [], [], []]
        rnd = np.random.rand
        randn = np.random.randn
        for i in range(self.COLS):
            e = float(env[i])
            if e < 2.0:
                continue
            n = int(3 + (e / max_h) * 20)
            for _ in range(n):
                length = (rnd() ** 1.7) * e
                x = xcol[i] + randn() * 1.4
                ud = 1.0 if rnd() < 0.5 else -1.0
                y1 = cy + ud * length
                x1 = x + randn() * 0.9
                a = 1.0 - (length / e) * 0.72  # short strands = darker
                b = min(3, max(0, int(a * 4)))
                buckets[b].append(QLineF(x, cy, x1, y1))
        return buckets

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(18, 12, w - 36, h - 34)
        radius = 28.0

        # soft drop shadow (3D float)
        for i in range(14, 0, -1):
            sr = QRectF(rect).adjusted(-i, -i, i, i)
            sr.translate(0, 6)
            a = max(0, int(9 - i * 0.7))
            if a <= 0:
                continue
            sp = QPainterPath()
            sp.addRoundedRect(sr, radius + i, radius + i)
            p.fillPath(sp, QColor(0, 0, 0, a))

        # warm parchment body (lo-fi paper)
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bg.setColorAt(0.0, QColor(244, 242, 235, 240))
        bg.setColorAt(1.0, QColor(232, 229, 219, 242))
        p.fillPath(body, bg)

        p.setClipPath(body)
        # the sand strands, drawn in 4 opacity tiers
        buckets = self._strand_buckets(rect)
        for tier, lines in enumerate(buckets):
            if not lines:
                continue
            pen = QPen(QColor(INK[0], INK[1], INK[2], ALPHA_BUCKETS[tier]), 0.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLines(lines)
        p.setClipping(False)

        # subtle warm hairline border
        p.setPen(QPen(QColor(120, 110, 95, 90), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()
