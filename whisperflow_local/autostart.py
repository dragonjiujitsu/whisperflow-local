"""Launch-on-login support for the installed bundle or development interpreter."""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from .paths import BUNDLE_ID

_LAUNCH_AGENT_LABEL = BUNDLE_ID
_LAUNCH_AGENT_NAME = f"{_LAUNCH_AGENT_LABEL}.plist"


def _path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / _LAUNCH_AGENT_NAME


def is_installed() -> bool:
    return _path().exists()


def install() -> str:
    plist = _path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    executable = Path(sys.executable).resolve()
    # Frozen apps run their own bundle executable directly. Development keeps a
    # module argument but never relies on a repository working directory.
    arguments = [str(executable)]
    if not getattr(sys, "frozen", False) and ".app/Contents/MacOS/" not in str(executable):
        arguments.extend(["-m", "whisperflow_local", "run"])
    payload = {
        "Label": _LAUNCH_AGENT_LABEL,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / "whisperflow-local.out.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / "whisperflow-local.err.log"),
    }
    with open(plist, "wb") as fh:
        plistlib.dump(payload, fh)
    plist.chmod(0o600)
    return str(plist)


def uninstall() -> bool:
    plist = _path()
    if plist.exists():
        plist.unlink()
        return True
    return False
