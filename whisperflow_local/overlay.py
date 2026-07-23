"""Non-activating, mouse-transparent voice pill overlay for macOS.

The overlay stays above other windows, avoids keyboard focus, and lets mouse
events pass through to the app underneath.
"""
from __future__ import annotations

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

INK = (24, 24, 28)  # near-black threads


def voice_pill_window_flags() -> Qt.WindowType:
    """An independent overlay that remains visible while this UIElement is inactive.

    ``Qt.Tool`` windows are hidden by macOS when their application is not
    active. WhisperFlow is an LSUIElement and intentionally stays inactive
    during dictation, so the pill must be a normal top-level window while still
    refusing focus and activation.
    """
    return (
        Qt.FramelessWindowHint
        | Qt.WindowStaysOnTopHint
        | Qt.Window
        | Qt.WindowDoesNotAcceptFocus
    )


class VoicePill(QWidget):
    """Flowing-thread waveform pill. ``set_level(rms)`` (0..1) drives amplitude;
    never steals focus."""

    PTS = 96

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(voice_pill_window_flags())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.resize(440, 150)

        self._level = 0.0
        self._raw_level = 0.0
        self._smooth = 0.0
        self._device_name = "System default"
        self._t = 0.0
        self._error = False  # red failure flash (no text was inserted)

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
        self._tick.setInterval(50)  # 20 fps keeps global shortcuts responsive

    # -- public API -----------------------------------------------------------
    @Slot(float)
    def set_level(self, rms: float) -> None:
        self._raw_level = max(0.0, float(rms))
        self._level = min(1.0, (self._raw_level * 7.0) ** 0.55)

    def set_device_name(self, name: str) -> None:
        self._device_name = name or "System default"

    def show_pill(self) -> None:
        # clear any in-flight error flash so its pending hide-timer no-ops
        # instead of yanking the pill out of a fresh recording
        self._error = False
        self._position_bottom_center()
        self.show()
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

        contour = self._contour(fx, t)
        y = cy + contour * amp * edge
        poly = QPolygonF([QPointF(xs[k], y[k]) for k in range(self.PTS)])
        # Three strokes over one geometry give depth without the previous
        # 4,928-point, 56-draw-call renderer that starved the Qt event loop.
        for color, width in (
            (QColor(INK[0], INK[1], INK[2], 24), 7.0),
            (QColor(INK[0], INK[1], INK[2], 80), 2.6),
            (QColor(INK[0], INK[1], INK[2], 185), 0.9),
        ):
            pen = QPen(color, width)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(poly)

        p.setClipping(False)

        # Explicit capture identity and signal health: the waveform remains the
        # expressive visual, while this meter answers "is real sound flowing?"
        p.setPen(QColor(48, 45, 40, 220))
        font = p.font(); font.setPointSize(9); font.setBold(True); p.setFont(font)
        device = self._device_name
        if len(device) > 34:
            device = device[:31] + "…"
        p.drawText(
            QRectF(rect.left() + 14, rect.top() + 8, rect.width() - 100, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"LISTENING · {device}",
        )
        signal_ok = self._raw_level >= 0.003
        p.setPen(QColor(28, 112, 67, 230) if signal_ok else QColor(151, 91, 25, 230))
        p.drawText(
            QRectF(rect.right() - 84, rect.top() + 8, 70, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "SIGNAL" if signal_ok else "QUIET",
        )
        segment_count = 14
        active = min(segment_count, int(round(self._level * segment_count)))
        segment_width = (rect.width() - 28 - (segment_count - 1) * 4) / segment_count
        y = rect.bottom() - 14
        for index in range(segment_count):
            x = rect.left() + 14 + index * (segment_width + 4)
            color = (
                QColor(47, 137, 83, 220)
                if index < active else QColor(85, 78, 67, 45)
            )
            p.fillRect(QRectF(x, y, segment_width, 5), color)

        # hairline border — warm normally, red on failure
        if self._error:
            p.setPen(QPen(QColor(176, 58, 48, 210), 1.8))
        else:
            p.setPen(QPen(QColor(116, 106, 88, 130), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()
