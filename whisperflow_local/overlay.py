"""Non-activating, click-through voice pill overlay (PySide6 + Win32).

The critical contract (PLAN.md spike 1): this window must
  - stay always-on-top,
  - NEVER take keyboard focus (so paste lands in the user's text field), and
  - pass mouse clicks through to whatever is behind it.

Qt window flags/attributes get the cross-platform 80%; the Win32 extended styles
(WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW) stamped
on the HWND give the hard guarantees.

Visuals: a flowing "thread field" — dozens of fine translucent lines tracing a
mic-reactive waveform contour with per-thread jitter, overlapping into a silky,
smoke-like ribbon with sharp peaks. Light/airy aesthetic.
"""
from __future__ import annotations

import sys

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QWidget

# --- Win32 extended-style constants ------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080

INK = (24, 24, 28)  # near-black threads


def _apply_passthrough_styles(hwnd: int) -> None:
    import win32gui

    ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex)


class VoicePill(QWidget):
    """Flowing-thread waveform pill. ``set_level(rms)`` (0..1) drives amplitude;
    never steals focus."""

    THREADS = 56
    PTS = 88  # points per thread polyline

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(440, 150)

        self._level = 0.0
        self._smooth = 0.0
        self._t = 0.0
        self._error = False  # red failure flash (no text was inserted)

        # stable per-thread character (seeded once so threads don't flicker)
        rng = np.random.default_rng(7)
        self._amp_scale = 0.45 + 0.85 * rng.random(self.THREADS)
        self._phase = rng.random(self.THREADS) * 2 * np.pi
        self._voff = (rng.random(self.THREADS) - 0.5)   # vertical spread factor
        self._wfreq = 2.0 + 6.0 * rng.random(self.THREADS)  # wisp frequency
        self._wphase = rng.random(self.THREADS) * 2 * np.pi
        self._drift = (rng.random(self.THREADS) - 0.5) * 0.6
        self._fx = np.linspace(0.0, 1.0, self.PTS)

        # static fine paper grain (built once)
        gw, gh = self.width(), self.height()
        self._grain_arr = np.ascontiguousarray(
            np.random.default_rng(3).integers(0, 256, (gh, gw), dtype=np.uint8)
        )
        self._grain_img = QImage(self._grain_arr.data, gw, gh, gw,
                                 QImage.Format_Grayscale8)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)
        self._tick.setInterval(33)  # ~30 fps

    # -- public API -----------------------------------------------------------
    @Slot(float)
    def set_level(self, rms: float) -> None:
        self._level = max(0.0, min(1.0, rms))

    def show_pill(self) -> None:
        # clear any in-flight error flash so its pending hide-timer no-ops
        # instead of yanking the pill out of a fresh recording
        self._error = False
        self._position_bottom_center()
        self.show()
        if sys.platform == "win32":
            _apply_passthrough_styles(int(self.winId()))
        self._tick.start()

    def hide_pill(self) -> None:
        self._tick.stop()
        self.hide()

    @Slot()
    def flash_error(self) -> None:
        """Briefly show the pill in a red 'failed — nothing inserted' state, then
        hide. Safe to call when the pill is already hidden (post-processing)."""
        self._error = True
        self._smooth = 0.0
        self._level = 0.0
        self._position_bottom_center()
        self.show()
        if sys.platform == "win32":
            _apply_passthrough_styles(int(self.winId()))
        self._tick.start()
        QTimer.singleShot(900, self._end_error)

    def _end_error(self) -> None:
        # only tear down if still in the error state; a new recording (show_pill)
        # clears _error and must not be hidden by this stale one-shot
        if self._error:
            self._error = False
            self.hide_pill()

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

    def _contour(self, fx: np.ndarray, t: float) -> np.ndarray:
        """Base waveform shape with a few sharp transient peaks."""
        base = (
            0.50 * np.sin(2 * np.pi * 1.6 * fx + t * 1.0)
            + 0.30 * np.sin(2 * np.pi * 2.7 * fx - t * 0.7)
            + 0.20 * np.sin(2 * np.pi * 4.3 * fx + t * 1.3)
        )
        # moving sharp spikes (narrow gaussians) for the spiky-peak character
        spikes = np.zeros_like(fx)
        for k in range(3):
            c = (0.5 + 0.5 * np.sin(t * (0.5 + 0.4 * k) + k * 2.0))
            spikes += (0.6 - 0.18 * k) * np.exp(-((fx - c) ** 2) / (2 * 0.0016))
            spikes -= (0.4 - 0.1 * k) * np.exp(-((fx - (1 - c)) ** 2) / (2 * 0.0016))
        return base + 0.5 * spikes

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(18, 12, w - 36, h - 34)
        radius = 16.0  # softer rounded rect (less full-pill, more app-card)

        # soft drop shadow (a bit deeper for lift on a light bg)
        for i in range(16, 0, -1):
            sr = QRectF(rect).adjusted(-i, -i, i, i)
            sr.translate(0, 7)
            a = max(0, int(13 - i * 0.75))
            if a <= 0:
                continue
            sp = QPainterPath()
            sp.addRoundedRect(sr, radius + i, radius + i)
            p.fillPath(sp, QColor(0, 0, 0, a))

        # body: warm cream normally; a soft red wash on failure
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if self._error:
            bg.setColorAt(0.0, QColor(238, 206, 200, 244))
            bg.setColorAt(1.0, QColor(226, 188, 181, 246))
        else:
            bg.setColorAt(0.0, QColor(240, 234, 223, 242))
            bg.setColorAt(1.0, QColor(228, 221, 207, 244))
        p.fillPath(body, bg)

        p.setClipPath(body)

        # paper texture (static, a bit more present)
        p.setOpacity(0.10)
        p.setCompositionMode(QPainter.CompositionMode_Overlay)
        p.drawImage(self.rect(), self._grain_img)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setOpacity(1.0)

        left = rect.left() + 20
        width = rect.width() - 40
        cy = rect.center().y()
        max_h = rect.height() / 2 - 10
        amp = max_h * (0.14 + 0.86 * self._smooth)
        t = self._t
        fx = self._fx
        xs = left + fx * width
        edge = np.sin(np.pi * fx) ** 0.7  # taper ends to zero

        base_contour = self._contour(fx, t)

        for j in range(self.THREADS):
            # per-thread wisp: amplitude, phase drift, vertical spread, wobble
            c = self._contour(fx, t + self._drift[j])
            wob = np.sin(2 * np.pi * self._wfreq[j] * fx + self._wphase[j] + t * 1.1)
            spread = (max_h * 0.5) * self._voff[j] * (0.25 + 0.75 * abs(base_contour))
            y = (
                cy
                + c * amp * self._amp_scale[j] * edge
                + spread * edge
                + wob * (amp * 0.10) * edge
            )
            poly = QPolygonF([QPointF(xs[k], y[k]) for k in range(self.PTS)])
            alpha = 14 + int(26 * self._amp_scale[j] / 1.3)
            pen = QPen(QColor(INK[0], INK[1], INK[2], alpha), 0.7)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPolyline(poly)

        p.setClipping(False)

        # hairline border — warm normally, red on failure
        if self._error:
            p.setPen(QPen(QColor(176, 58, 48, 210), 1.8))
        else:
            p.setPen(QPen(QColor(116, 106, 88, 130), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()
