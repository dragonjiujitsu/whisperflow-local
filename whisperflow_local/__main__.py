"""CLI entrypoint: doctor | run | selftest."""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .config import load_config

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "samples" / "test.wav"
SAMPLE_TEXT = (
    "um so like I was thinking you know maybe we could uh ship the the feature "
    "tomorrow morning if that works for everyone"
)


# --------------------------------------------------------------------------- #
# audio helpers
# --------------------------------------------------------------------------- #
def load_wav_16k_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data[::ch]
    if sr != 16000:
        # linear resample to 16k
        tgt = int(len(data) * 16000 / sr)
        data = np.interp(
            np.linspace(0, len(data), tgt, endpoint=False),
            np.arange(len(data)),
            data,
        ).astype(np.float32)
    return data, 16000


def ensure_sample() -> bool:
    if SAMPLE.exists():
        return True
    SAMPLE.parent.mkdir(exist_ok=True)
    try:
        import win32com.client

        voice = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(SAMPLE), 3, False)  # SSFMCreateForWrite
        voice.AudioOutputStream = stream
        voice.Speak(SAMPLE_TEXT)
        stream.Close()
        return SAMPLE.exists()
    except Exception as exc:
        print(f"[error] could not generate sample via SAPI: {exc}")
        return False


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def doctor() -> int:
    cfg = load_config()
    checks: list[tuple[str, bool, str]] = []

    # mic
    try:
        import sounddevice as sd

        ins = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        checks.append(("microphone", len(ins) > 0, f"{len(ins)} input device(s)"))
    except Exception as exc:
        checks.append(("microphone", False, str(exc)))

    # CUDA via ctranslate2
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        checks.append(("cuda", n > 0, f"{n} CUDA device(s)"))
    except Exception as exc:
        checks.append(("cuda", False, str(exc)))

    # ollama on localhost + model present
    try:
        import os

        import ollama

        host = os.environ.get("OLLAMA_HOST", "127.0.0.1")
        loopback = ("127.0.0.1" in host) or ("localhost" in host) or host in ("", "127.0.0.1")
        client = ollama.Client()
        names = [m.model for m in client.list().models]
        want = cfg.cleanup["model"]
        present = any(want in n for n in names)
        checks.append(("ollama", present, f"model {want} {'present' if present else 'MISSING'}"))
        if not loopback:
            checks.append(("ollama-loopback", False, f"OLLAMA_HOST={host} not loopback"))
    except Exception as exc:
        checks.append(("ollama", False, str(exc)))

    # clipboard
    try:
        import pyperclip

        pyperclip.paste()
        checks.append(("clipboard", True, "ok"))
    except Exception as exc:
        checks.append(("clipboard", False, str(exc)))

    # hotkey + overlay import
    try:
        from . import hotkey, overlay  # noqa: F401

        checks.append(("hotkey+overlay", True, "import ok"))
    except Exception as exc:
        checks.append(("hotkey+overlay", False, str(exc)))

    # reserved Win+<letter> freed? (only relevant for <cmd>+letter combos)
    try:
        from . import winhotkey

        letter = winhotkey.win_letter(cfg.hotkey_combo)
        if letter is None:
            checks.append(("hotkey-reserved", True, f"{cfg.hotkey_combo} not a Win+letter combo"))
        else:
            freed = winhotkey.is_disabled(letter)
            checks.append((
                "hotkey-reserved",
                freed,
                f"Win+{letter} {'freed' if freed else 'NOT freed — run `run` once to apply'}",
            ))
    except Exception as exc:
        checks.append(("hotkey-reserved", False, str(exc)))

    print("--- doctor ---")
    ok_all = True
    for name, ok, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")
        ok_all = ok_all and ok
    print(f"\ndoctor {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


# --------------------------------------------------------------------------- #
# selftest: full pipeline on a spoken sample, paste into a real focused field
# --------------------------------------------------------------------------- #
def selftest() -> int:
    cfg = load_config()
    results: dict[str, bool] = {}

    results["1_sample"] = ensure_sample()
    if not results["1_sample"]:
        return _report(results)

    audio, sr = load_wav_16k_mono(SAMPLE)

    # STT
    from .stt import Transcriber

    stt = Transcriber(cfg.stt)
    transcript = stt.transcribe(audio, sr)
    print(f"[stt] {transcript!r}")
    results["2_stt_nonempty"] = bool(transcript.strip())

    # cleanup
    from .cleanup import Cleaner

    cleaner = Cleaner(cfg.cleanup)
    cleaned = cleaner.clean(transcript)
    print(f"[cleanup] {cleaned!r}")
    results["3_cleanup_nonempty"] = bool(cleaned.strip())
    # cleanup should drop at least one filler token
    fillers = ("um", "uh")
    results["3b_filler_reduced"] = (
        sum(transcript.lower().count(f) for f in fillers)
        > sum(cleaned.lower().count(f) for f in fillers)
    )

    # focus-safe insert into a REAL focused text field
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QTextEdit

    from .inserter import Inserter, capture_focus_target

    app = QApplication.instance() or QApplication(sys.argv)
    edit = QTextEdit()
    edit.setWindowTitle("whisperflow selftest target")
    edit.resize(500, 200)
    edit.show()
    edit.raise_()
    edit.activateWindow()
    edit.setFocus()

    import threading

    inserter = Inserter(cfg.insert)
    state = {"ok": False, "reason": "", "text": "", "fg": ""}
    hwnd = int(edit.winId())

    def do_insert():
        # force the test window to the foreground so the synthetic Ctrl+V
        # lands here and not in the launching console
        import win32gui

        try:
            _force_foreground(hwnd)
        except Exception:
            pass
        edit.setFocus()
        state["fg"] = win32gui.GetWindowText(win32gui.GetForegroundWindow())

        # Run insertion on a WORKER thread (mirrors the real app) so the Qt
        # event loop stays free to process the synthetic Ctrl+V while the
        # cleaned text is still on the clipboard (before restore).
        def worker():
            target = capture_focus_target()
            ok, reason = inserter.insert(cleaned, target)
            state["ok"], state["reason"] = ok, reason

        threading.Thread(target=worker, daemon=True).start()
        QTimer.singleShot(1500, finish)

    def finish():
        state["text"] = edit.toPlainText()
        app.quit()

    QTimer.singleShot(600, do_insert)
    app.exec()

    print(f"[insert] ok={state['ok']} reason={state['reason']} fg={state['fg']!r} got={state['text']!r}")
    results["4_inserted_into_field"] = state["ok"] and cleaned.split()[0].lower() in state["text"].lower()

    return _report(results)


def _force_foreground(hwnd: int) -> None:
    """Reliably bring a window to the foreground on Windows by attaching to the
    current foreground thread's input queue (SetForegroundWindow alone is
    refused for background processes)."""
    import ctypes

    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    fg_thread = u.GetWindowThreadProcessId(fg, None)
    cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    u.AttachThreadInput(cur_thread, fg_thread, True)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        u.AttachThreadInput(cur_thread, fg_thread, False)


def _report(results: dict[str, bool]) -> int:
    print("\n--- SELFTEST RESULTS ---")
    ok_all = True
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        ok_all = ok_all and ok
    print(f"\nSELFTEST {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


# --------------------------------------------------------------------------- #
def run() -> int:
    """Launch the live app (hotkey-driven). Use Ctrl+C to quit."""
    from PySide6.QtWidgets import QApplication

    from .app import Controller
    from .hotkey import HotkeyListener

    cfg = load_config()

    # free a reserved Win+<letter> combo (e.g. Win+F) before binding the hotkey;
    # no-op unless the combo is Win+letter and not already freed.
    from . import winhotkey

    changed, msg = winhotkey.ensure_freed(cfg.hotkey_combo)
    print(f"[run] hotkey: {msg}")
    if changed:
        print("[run] Explorer was restarted to apply the hotkey change.")

    qapp = QApplication.instance() or QApplication(sys.argv)
    ctrl = Controller(cfg)
    print("[run] warming up models...")
    ctrl.warmup()
    listener = HotkeyListener(cfg.hotkey_combo, ctrl.on_hotkey)
    listener.start()
    print(f"[run] ready. Toggle with {cfg.hotkey_combo}. Ctrl+C to quit.")
    try:
        return qapp.exec()
    finally:
        listener.stop()


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "doctor":
        return doctor()
    if cmd == "selftest":
        return selftest()
    if cmd == "run":
        return run()
    print(f"unknown command: {cmd}\nusage: python -m whisperflow_local [doctor|run|selftest]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
