"""SPIKE 1 (PLAN.md de-risk step 1): prove the overlay never steals focus and
is click-through, on this Win11 box.

Acceptance, all must hold:
  A. GetForegroundWindow() is UNCHANGED after the pill is shown + animated.
  B. The pill's HWND carries WS_EX_NOACTIVATE and WS_EX_TRANSPARENT.
  C. The pill's HWND is NOT the foreground window.

Prints PASS/FAIL per check and a final verdict, then exits (code 0 = all pass).
Runs headless-friendly: shows the pill for ~1.2s, then quits automatically.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp1252; window titles can contain arbitrary
# Unicode. Make stdout tolerant so logging a title never crashes the spike.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# allow running directly: python spikes/spike_overlay.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import win32gui  # noqa: E402

from whisperflow_local.overlay import (  # noqa: E402
    GWL_EXSTYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    VoicePill,
)


def main() -> int:
    app = QApplication(sys.argv)

    fg_before = win32gui.GetForegroundWindow()
    print(f"[info] foreground before show: hwnd={fg_before} "
          f"title={win32gui.GetWindowText(fg_before)!r}")

    pill = VoicePill()
    pill.show_pill()

    # drive a few fake levels so the animation + paint path actually run
    levels = iter([0.2, 0.6, 0.9, 0.5, 0.3, 0.8, 0.1])

    def feed():
        try:
            pill.set_level(next(levels))
        except StopIteration:
            pass

    feeder = QTimer()
    feeder.timeout.connect(feed)
    feeder.start(120)

    results: dict[str, bool] = {}

    def check_and_quit():
        fg_after = win32gui.GetForegroundWindow()
        pill_hwnd = int(pill.winId())
        ex = win32gui.GetWindowLong(pill_hwnd, GWL_EXSTYLE)

        results["A_focus_unchanged"] = fg_after == fg_before
        results["B_noactivate_style"] = bool(ex & WS_EX_NOACTIVATE)
        results["B_transparent_style"] = bool(ex & WS_EX_TRANSPARENT)
        results["C_pill_not_foreground"] = fg_after != pill_hwnd

        print(f"[info] foreground after show:  hwnd={fg_after} "
              f"title={win32gui.GetWindowText(fg_after)!r}")
        print(f"[info] pill hwnd={pill_hwnd}  ex_style=0x{ex:08x}")

        pill.hide_pill()
        app.quit()

    QTimer.singleShot(1200, check_and_quit)
    app.exec()

    print("\n--- SPIKE 1 RESULTS ---")
    all_ok = True
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        all_ok = all_ok and ok

    print(f"\nSPIKE 1 {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
