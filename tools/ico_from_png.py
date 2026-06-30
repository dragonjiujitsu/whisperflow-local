"""Build a multi-size Windows .ico (and a 256 PNG) from a source PNG.

Used to turn the chosen hero logo (assets/logo.png, the Higgsfield-refined sand
pill) into the app/tray icon. Scales with smooth filtering and embeds each size
as a PNG-compressed ICO entry (Windows Vista+).

Run: python tools/ico_from_png.py assets/logo.png
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets"
SIZES = [16, 32, 48, 64, 128, 256]


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def _scaled(src: QImage, size: int) -> QImage:
    return src.scaled(
        size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    ).convertToFormat(QImage.Format_ARGB32)


def main() -> None:
    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "logo.png"
    QGuiApplication([])
    src = QImage(str(src_path))
    if src.isNull():
        raise SystemExit(f"could not load {src_path}")

    # 256 PNG for general use
    _scaled(src, 256).save(str(ASSETS / "icon.png"), "PNG")

    # multi-size ICO with PNG entries
    pngs = [(s, _png_bytes(_scaled(src, s))) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + len(pngs) * 16
    entries = b""
    data = b""
    for s, png in pngs:
        b = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    (ASSETS / "icon.ico").write_bytes(header + entries + data)

    print(f"wrote {ASSETS / 'icon.png'}")
    print(f"wrote {ASSETS / 'icon.ico'} from {src_path.name}")


if __name__ == "__main__":
    main()
