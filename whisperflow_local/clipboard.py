"""macOS clipboard helpers using the system pasteboard commands."""
from __future__ import annotations

import subprocess


def paste() -> str:
    proc = subprocess.run(
        ["pbpaste"],
        check=True,
        capture_output=True,
        text=True,
        timeout=1.0,
    )
    return proc.stdout


def copy(text: str) -> None:
    subprocess.run(
        ["pbcopy"],
        input=text,
        check=True,
        text=True,
        timeout=1.0,
    )
