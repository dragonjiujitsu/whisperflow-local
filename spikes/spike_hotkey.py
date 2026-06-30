"""SPIKE 2 (PLAN.md de-risk step 2): prove the global toggle hotkey registers
and drives the state machine.

Acceptance:
  A. Registering ``<ctrl>+<alt>+<space>`` succeeds.
  B. Two synthetic activations fire the callback twice.
  C. The toggle walks IDLE -> RECORDING -> IDLE.

This proves the WIRING. Real cross-app reliability (Chrome, Electron,
terminals, IME fields) still needs a human pass per PLAN.md.

Prints PASS/FAIL, exits (0 = all pass).
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

from pynput.keyboard import Controller, Key  # noqa: E402

from whisperflow_local.hotkey import HotkeyListener  # noqa: E402

COMBO = "<ctrl>+<alt>+<space>"


def main() -> int:
    state = {"value": "IDLE"}
    activations = {"count": 0}
    transitions: list[str] = []

    def on_activate() -> None:
        activations["count"] += 1
        state["value"] = "RECORDING" if state["value"] == "IDLE" else "IDLE"
        transitions.append(state["value"])

    results: dict[str, bool] = {}
    try:
        listener = HotkeyListener(COMBO, on_activate)
        listener.start()
        results["A_registered"] = True
    except Exception as exc:  # pragma: no cover
        print(f"[error] registration failed: {exc}")
        results["A_registered"] = False
        _report(results)
        return 1

    kb = Controller()

    def press_combo() -> None:
        kb.press(Key.ctrl)
        kb.press(Key.alt)
        kb.press(Key.space)
        time.sleep(0.05)
        kb.release(Key.space)
        kb.release(Key.alt)
        kb.release(Key.ctrl)

    def driver() -> None:
        time.sleep(0.6)  # let the listener thread settle
        press_combo()
        time.sleep(0.4)
        press_combo()
        time.sleep(0.4)

    t = threading.Thread(target=driver)
    t.start()
    t.join(timeout=5)

    listener.stop()
    time.sleep(0.1)

    results["B_fired_twice"] = activations["count"] == 2
    results["C_toggled_idle_rec_idle"] = transitions == ["RECORDING", "IDLE"]

    print(f"[info] activations={activations['count']} transitions={transitions}")
    return _report(results)


def _report(results: dict[str, bool]) -> int:
    print("\n--- SPIKE 2 RESULTS ---")
    all_ok = True
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        all_ok = all_ok and ok
    print(f"\nSPIKE 2 {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
