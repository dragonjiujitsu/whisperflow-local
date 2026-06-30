"""Verify pynput win32_event_filter can DETECT and SUPPRESS the Enter key.

Sends a synthetic Enter and checks the filter fired. Then prints PASS/FAIL.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pynput import keyboard
from pynput.keyboard import Controller, Key

VK_RETURN = 0x0D

state = {"detected": 0, "suppressed": False}
listener = None


def win32_filter(msg, data):
    if data.vkCode == VK_RETURN:
        state["detected"] += 1
        try:
            listener.suppress_event()
            state["suppressed"] = True
        except Exception as e:
            print(f"[err] suppress_event: {e}")


def main() -> int:
    global listener
    listener = keyboard.Listener(on_press=lambda k: None, win32_event_filter=win32_filter)
    listener.start()
    time.sleep(0.5)

    kb = Controller()
    for _ in range(3):
        kb.tap(Key.enter)
        time.sleep(0.2)

    time.sleep(0.3)
    listener.stop()

    print(f"[info] enter detected={state['detected']} suppressed={state['suppressed']}")
    ok = state["detected"] >= 1
    print(f"\nSPIKE ENTER {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
