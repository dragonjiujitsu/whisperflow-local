"""Render the app icon with the SAME brush as the voice pill.

Matching the pill (overlay.py) by construction: cream sand card, paper-grain
texture, a centered flowing ink-thread waveform, warm hairline border. Renders
offscreen via Qt (already a dependency) and writes:

    assets/icon.png   (256x256)
    assets/icon.ico   (multi-size: 16/32/48/64/128/256, PNG-compressed entries)

Run: python tools/make_icon.py
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets"

# palette lifted straight from overlay.py so the icon can't drift from the pill
INK = (24, 24, 28)
CREAM_TOP = (240, 234, 223)
CREAM_BOT = (228, 221, 207)
BORDER = (116, 106, 88)

THREADS = 40
PTS = 110


def _contour(fx: np.ndarray) -> np.ndarray:
    """A static, pleasing waveform shape (no live RMS) with a couple of peaks."""
    base = (
        0.50 * np.sin(2 * np.pi * 1.6 * fx + 0.4)
        + 0.30 * np.sin(2 * np.pi * 2.7 * fx - 0.7)
        + 0.20 * np.sin(2 * np.pi * 4.3 * fx + 1.3)
    )
    spikes = np.zeros_like(fx)
    for k, c in enumerate((0.40, 0.62)):
        spikes += (0.6 - 0.2 * k) * np.exp(-((fx - c) ** 2) / (2 * 0.0016))
    return base + 0.5 * spikes


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    s = size
    margin = s * 0.075
    rect = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)
    radius = s * 0.22

    # cream sand card
    body = QPainterPath()
    body.addRoundedRect(rect, radius, radius)
    bg = QLinearGradient(0, rect.top(), 0, rect.bottom())
    bg.setColorAt(0.0, QColor(*CREAM_TOP))
    bg.setColorAt(1.0, QColor(*CREAM_BOT))
    p.fillPath(body, bg)
    p.setClipPath(body)

    # paper grain (deterministic)
    gw = gh = size
    grain = np.ascontiguousarray(
        np.random.default_rng(3).integers(0, 256, (gh, gw), dtype=np.uint8)
    )
    gimg = QImage(grain.data, gw, gh, gw, QImage.Format_Grayscale8)
    p.setOpacity(0.10)
    p.setCompositionMode(QPainter.CompositionMode_Overlay)
    p.drawImage(QRectF(0, 0, s, s), gimg)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.setOpacity(1.0)

    # flowing ink-thread waveform, centered, tapered at the ends
    left = rect.left() + rect.width() * 0.16
    width = rect.width() * 0.68
    cy = rect.center().y()
    max_h = rect.height() * 0.30
    fx = np.linspace(0.0, 1.0, PTS)
    xs = left + fx * width
    edge = np.sin(np.pi * fx) ** 0.7
    base_c = _contour(fx)

    rng = np.random.default_rng(7)
    amp_scale = 0.45 + 0.85 * rng.random(THREADS)
    voff = rng.random(THREADS) - 0.5
    wfreq = 2.0 + 6.0 * rng.random(THREADS)
    wphase = rng.random(THREADS) * 2 * np.pi

    for j in range(THREADS):
        wob = np.sin(2 * np.pi * wfreq[j] * fx + wphase[j])
        spread = (max_h * 0.5) * voff[j] * (0.25 + 0.75 * np.abs(base_c))
        y = (
            cy
            + base_c * max_h * amp_scale[j] * edge
            + spread * edge
            + wob * (max_h * 0.10) * edge
        )
        poly = QPolygonF([QPointF(float(xs[k]), float(y[k])) for k in range(PTS)])
        alpha = 16 + int(30 * amp_scale[j] / 1.3)
        pen = QPen(QColor(INK[0], INK[1], INK[2], alpha), max(0.6, s / 360))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPolyline(poly)

    p.setClipping(False)

    # warm hairline border
    p.setPen(QPen(QColor(*BORDER, 150), max(1.0, s / 170)))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect, radius, radius)
    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, sizes: list[int]) -> None:
    """Minimal ICO writer with PNG-compressed entries (Windows Vista+)."""
    pngs = [(sz, _png_bytes(render(sz))) for sz in sizes]
    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)  # reserved, type=1(icon), count
    offset = 6 + n * 16
    entries = b""
    data = b""
    for sz, png in pngs:
        b = 0 if sz >= 256 else sz  # 0 means 256 in ICO
        entries += struct.pack(
            "<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset
        )
        data += png
        offset += len(png)
    path.write_bytes(header + entries + data)


def main() -> None:
    QGuiApplication([])
    ASSETS.mkdir(exist_ok=True)
    render(256).save(str(ASSETS / "icon.png"), "PNG")
    render(1024).save(str(ASSETS / "icon@1024.png"), "PNG")
    render(2048).save(str(ASSETS / "icon@2048.png"), "PNG")
    write_ico(ASSETS / "icon.ico", [16, 32, 48, 64, 128, 256])
    print(f"wrote {ASSETS / 'icon.png'}")
    print(f"wrote {ASSETS / 'icon@1024.png'}")
    print(f"wrote {ASSETS / 'icon@2048.png'}")
    print(f"wrote {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
