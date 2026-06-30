"""Free a reserved ``Win+<letter>`` shortcut so our global hotkey can use it.

Windows reserves combos like ``Win+F`` (Feedback Hub) at the Explorer level —
the keystroke is swallowed before any third-party hook (pynput) sees it. The
documented escape hatch is the per-user ``DisabledHotkeys`` value: a REG_SZ of
concatenated uppercase letters whose ``Win+<letter>`` combos Explorer stops
handling. Setting it requires an Explorer restart to take effect.

We only touch the registry when the configured combo is exactly ``<cmd>+<letter>``
and that letter is not already disabled, and we only restart Explorer when we
actually changed something — so steady-state launches are a no-op.
"""
from __future__ import annotations

import re
import winreg

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
_VALUE = "DisabledHotkeys"

# matches a combo that is exactly the Windows key + a single letter, e.g. "<cmd>+f"
_WIN_LETTER = re.compile(r"^<cmd>\+([a-z])$", re.IGNORECASE)


def win_letter(combo: str) -> str | None:
    """Return the uppercase letter if ``combo`` is ``<cmd>+<letter>``, else None."""
    m = _WIN_LETTER.match(combo.strip())
    return m.group(1).upper() if m else None


def read_disabled() -> str:
    """Current DisabledHotkeys string (uppercase letters), or '' if unset."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as k:
            val, _ = winreg.QueryValueEx(k, _VALUE)
            return str(val).upper()
    except FileNotFoundError:
        return ""


def is_disabled(letter: str) -> bool:
    return letter.upper() in read_disabled()


def _write_disabled(letters: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEY) as k:
        winreg.SetValueEx(k, _VALUE, 0, winreg.REG_SZ, letters)


def restart_explorer() -> None:
    """Restart Explorer so a DisabledHotkeys change takes effect.

    Disruptive (taskbar + open File Explorer windows flash), so callers should
    only invoke this when the registry actually changed.
    """
    import subprocess

    subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True)
    subprocess.Popen(["explorer.exe"])


def ensure_freed(combo: str, *, restart: bool = True) -> tuple[bool, str]:
    """Ensure the combo's ``Win+<letter>`` is freed at the Explorer level.

    Returns ``(changed, message)``. ``changed`` is True only when we wrote the
    registry (and, if ``restart``, bounced Explorer). For combos that are not
    ``<cmd>+<letter>`` this is a no-op.
    """
    letter = win_letter(combo)
    if letter is None:
        return False, f"{combo} is not a Win+letter combo; nothing to free"
    cur = read_disabled()
    if letter in cur:
        return False, f"Win+{letter} already freed (DisabledHotkeys={cur!r})"
    new = cur + letter
    _write_disabled(new)
    if restart:
        restart_explorer()
        return True, f"freed Win+{letter} (DisabledHotkeys={new!r}); Explorer restarted"
    return True, f"freed Win+{letter} (DisabledHotkeys={new!r}); restart Explorer to apply"
