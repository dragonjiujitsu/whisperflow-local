"""Launch-on-login via a Startup-folder shortcut (Windows).

Writes a ``.lnk`` into the per-user Startup folder that runs the app windowless
(``pythonw.exe -m whisperflow_local run``) from the repo directory. No registry
edits, no admin — drop the shortcut to uninstall. ``pythonw`` (not ``python``)
so there's no console window; the tray icon is the only visible surface.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LNK_NAME = "WhisperFlowLocal.lnk"
_REPO = Path(__file__).resolve().parents[1]


def _startup_dir() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def _lnk_path() -> Path:
    return _startup_dir() / _LNK_NAME


def _pythonw() -> Path:
    """The windowless interpreter sibling of the current python.exe."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return pyw if pyw.exists() else exe  # fall back to python.exe if absent


def is_installed() -> bool:
    return _lnk_path().exists()


def install() -> str:
    import win32com.client  # pywin32, already a dependency

    lnk = _lnk_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(str(lnk))
    sc.TargetPath = str(_pythonw())
    sc.Arguments = "-m whisperflow_local run"
    sc.WorkingDirectory = str(_REPO)
    sc.WindowStyle = 7  # minimized (pythonw has no window anyway)
    sc.Description = "whisperflow-local local dictation (launch on login)"
    sc.Save()
    return str(lnk)


def uninstall() -> bool:
    lnk = _lnk_path()
    if lnk.exists():
        lnk.unlink()
        return True
    return False
