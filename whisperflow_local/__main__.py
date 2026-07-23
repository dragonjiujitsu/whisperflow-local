"""CLI entrypoint: doctor | run | selftest."""
from __future__ import annotations

import importlib.util
import getpass
import os
import shutil
import shlex
import subprocess
import sys
import threading
import time
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
    return _ensure_sample_macos()


def _ensure_sample_macos() -> bool:
    aiff = SAMPLE.with_suffix(".aiff")
    try:
        subprocess.run(["say", "-o", str(aiff), SAMPLE_TEXT], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(SAMPLE)], check=True)
        return SAMPLE.exists()
    except Exception as exc:
        print(f"[error] could not generate sample via say/afconvert: {exc}")
        return False
    finally:
        try:
            aiff.unlink()
        except OSError:
            pass



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

    # Native TCC permission state. Device discovery alone is not proof that
    # recording and global insertion are authorized for this app identity.
    try:
        from .platform.macos.permissions import MacPermissions

        permissions = MacPermissions().report()
        checks.append((
            "permission-microphone",
            permissions.microphone.value == "authorized",
            permissions.microphone.value,
        ))
        checks.append((
            "permission-accessibility",
            permissions.accessibility.value == "authorized",
            permissions.accessibility.value,
        ))
    except Exception as exc:
        checks.append(("permissions", False, str(exc)))

    # STT backend
    installed = importlib.util.find_spec("lightning_whisper_mlx") is not None
    checks.append((
        "stt-mlx",
        sys.platform == "darwin" and installed,
        f"package {'installed' if installed else 'MISSING'}; platform={sys.platform}",
    ))

    # cleanup provider + model present
    provider = str(cfg.cleanup.get("provider", "ollama")).lower()
    want = cfg.cleanup["model"]
    fallback_provider = str(cfg.cleanup.get("fallback_provider", "")).lower()
    model_path = Path(str(cfg.cleanup.get("model_path") or want)).expanduser()

    if provider == "unsloth-cli":
        checks.append((
            "unsloth-cli",
            shutil.which("unsloth") is not None and model_path.exists(),
            f"cli {'found' if shutil.which('unsloth') else 'MISSING'}; model {model_path}",
        ))
    elif provider == "ollama":
        try:
            import os

            import ollama

            host = os.environ.get("OLLAMA_HOST", "127.0.0.1")
            loopback = ("127.0.0.1" in host) or ("localhost" in host) or host in ("", "127.0.0.1")
            client = ollama.Client()
            names = [m.model for m in client.list().models]
            present = any(want in n for n in names)
            checks.append(("ollama", present, f"model {want} {'present' if present else 'MISSING'}"))
            if not loopback:
                checks.append(("ollama-loopback", False, f"OLLAMA_HOST={host} not loopback"))
        except Exception as exc:
            checks.append(("ollama", False, str(exc)))
    elif provider in {"openai-compatible", "omlx"}:
        try:
            import json
            import os
            from urllib import request

            base_url = str(cfg.cleanup.get("base_url", "http://localhost:8888/v1")).rstrip("/")
            env_name = str(cfg.cleanup.get("api_key_env", "")).strip()
            api_key = os.environ.get(env_name, "").strip() if env_name else ""
            api_key = api_key or str(cfg.cleanup.get("api_key", "")).strip()
            if not api_key:
                from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore

                account = str(
                    cfg.cleanup.get("api_key_keychain_account")
                    or CLEANUP_API_KEY_ACCOUNT
                )
                api_key = KeychainSecretStore().get(account).strip()
            if not api_key:
                raise RuntimeError(f"missing API key; set cleanup.api_key or ${env_name}")
            req = request.Request(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                method="GET",
            )
            with request.urlopen(req, timeout=5.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            models = body.get("data") or body.get("models") or []
            names = [str(m.get("id") or m.get("name") or m) for m in models]
            present = (want == "default" and bool(names)) or any(want == n or want in n for n in names)
            detail = f"model {want} {'present' if present else 'MISSING'} at {base_url}"
            if want == "default" and names:
                detail = f"default -> {names[0]} at {base_url}"
            if not names:
                detail = f"no models reported at {base_url}"
            checks.append((provider, present, detail))
        except Exception as exc:
            if fallback_provider == "unsloth-cli":
                fallback_ok = shutil.which("unsloth") is not None and model_path.exists()
                detail = (
                    f"DEGRADED: server unavailable ({exc}); direct local fallback "
                    f"{'available' if fallback_ok else 'MISSING'}"
                )
                checks.append((provider, fallback_ok, detail))
            else:
                checks.append((provider, False, str(exc)))
    else:
        checks.append(("cleanup-provider", False, f"unsupported provider {provider!r}"))

    # clipboard
    try:
        from . import clipboard

        clipboard.paste()
        checks.append(("clipboard", True, "ok"))
    except Exception as exc:
        checks.append(("clipboard", False, str(exc)))

    # hotkey + overlay import
    try:
        from . import hotkey, overlay  # noqa: F401

        checks.append(("hotkey+overlay", True, "import ok"))
    except Exception as exc:
        checks.append(("hotkey+overlay", False, str(exc)))

    print("--- doctor ---")
    ok_all = True
    for name, ok, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")
        ok_all = ok_all and ok

    # autostart status (informational — not a pass/fail gate)
    try:
        from . import autostart

        state = "installed" if autostart.is_installed() else "not installed"
        print(f"  INFO autostart: {state} "
              f"(toggle: install-autostart / uninstall-autostart)")
    except Exception as exc:
        print(f"  INFO autostart: unknown ({exc})")

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
    # Cleanup should drop at least one filler/disfluency token.
    fillers = ("um", "uh", " like ", "you know")
    results["3b_filler_reduced"] = (
        sum(transcript.lower().count(f) for f in fillers)
        > sum(cleaned.lower().count(f) for f in fillers)
    )

    # Focus-safe insert into a real macOS text field.
    from .inserter import Inserter, capture_focus_target

    inserter = Inserter(cfg.insert)
    state = {"ok": False, "reason": "", "text": "", "fg": ""}
    try:
        if not _prepare_textedit_selftest_target():
            state["reason"] = "could not foreground TextEdit"
        else:
            state["fg"] = _foreground_title()
            target = capture_focus_target()
            ok, reason = inserter.insert(cleaned, target)
            state["ok"], state["reason"] = ok, reason
            time.sleep(0.5)
            state["text"] = _read_textedit_front_document()
    finally:
        _close_textedit_front_document()

    print(f"[insert] ok={state['ok']} reason={state['reason']} fg={state['fg']!r} got={state['text']!r}")
    results["4_inserted_into_field"] = state["ok"] and cleaned.split()[0].lower() in state["text"].lower()

    return _report(results)


def _force_foreground_macos() -> bool:
    try:
        import AppKit

        _make_process_activatable_macos()
        running = AppKit.NSRunningApplication.currentApplication()
        running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        time.sleep(0.2)
        if _foreground_pid() == str(os.getpid()):
            return True
    except Exception:
        pass

    script = 'tell application "System Events" to set frontmost of first process whose unix id is ' + str(os.getpid()) + ' to true'
    try:
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=30.0)
        return proc.returncode == 0
    except Exception:
        return False


def _prepare_textedit_selftest_target() -> bool:
    script = '''
tell application "TextEdit"
    activate
    make new document
end tell
delay 0.5
tell application "System Events" to set frontmost of first process whose name is "TextEdit" to true
'''
    try:
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=30.0)
        if proc.returncode != 0:
            return False
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if _foreground_title() == "TextEdit":
                return True
            time.sleep(0.15)
        return False
    except Exception:
        return False


def _read_textedit_front_document() -> str:
    script = 'tell application "TextEdit" to get text of front document'
    try:
        proc = subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=5.0)
        return proc.stdout.strip()
    except Exception:
        return ""


def _close_textedit_front_document() -> None:
    script = 'tell application "TextEdit" to if (count of documents) > 0 then close front document saving no'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True, timeout=5.0)
    except Exception:
        pass


def _make_process_activatable_macos() -> None:
    try:
        import AppKit

        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    except Exception:
        pass


def _foreground_title() -> str:
    script = 'tell application "System Events" to get name of first process whose frontmost is true'
    try:
        proc = subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=1.0)
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def _foreground_pid() -> str | None:
    script = 'tell application "System Events" to get unix id of first process whose frontmost is true'
    try:
        proc = subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=1.0)
        return proc.stdout.strip()
    except Exception:
        return None


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
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .app import Controller
    from .hotkey import HotkeyListener

    from PySide6.QtGui import QIcon

    from .diagnostics import DiagnosticsWindow, build_diagnostics
    from .model_manager import ModelManager
    from .onboarding import OnboardingWindow
    from .platform.macos.permissions import MacPermissions
    from .platform.macos.power import MacPowerMonitor
    from .settings_window import SettingsWindow
    from .recovery_window import RecoveryWindow
    from .tray import _ICON_FILE, make_tray, update_tray_status

    cfg = load_config()
    smoke_exit_ms = int(os.environ.get("WHISPERFLOW_SMOKE_EXIT_MS", "0") or 0)
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setApplicationName("WhisperFlow Local")
    qapp.setOrganizationName("Shawn Van Brunt")
    if _ICON_FILE.exists():
        qapp.setWindowIcon(QIcon(str(_ICON_FILE)))
    # the pill hides between dictations; don't let that quit the app
    qapp.setQuitOnLastWindowClosed(False)
    ctrl = Controller(cfg)
    service_manager = None
    if not smoke_exit_ms and str(cfg.cleanup.get("provider", "")).lower() in {
        "openai-compatible", "omlx"
    }:
        from .service import LocalServiceManager

        service_manager = LocalServiceManager(cfg.cleanup)
    listener = None
    if not smoke_exit_ms:
        listener = HotkeyListener(cfg.hotkey_combo, ctrl.on_hotkey)
        listener.start()

    permissions = MacPermissions()
    model_manager = ModelManager()
    onboarding = OnboardingWindow(permissions)
    settings_window = SettingsWindow(REPO / "config.yaml")
    recovery_window = RecoveryWindow(ctrl.recovery, ctrl.history)
    service_state = {"value": "starting" if service_manager else "fallback"}

    def show_window(window) -> None:
        window.show()
        window.raise_()
        window.activateWindow()

    def diagnostic_report():
        cleanup = cfg.cleanup
        model = model_manager.resolve_gguf(
            str(cleanup.get("server_model") or ""),
            str(cleanup.get("server_gguf_variant") or ""),
            str(cleanup.get("model_path") or ""),
        )
        return build_diagnostics(
            permissions.report(), model, service_state["value"]
        )

    diagnostics_window = DiagnosticsWindow(diagnostic_report)

    def quit_app() -> None:
        ctrl.on_system_event("quit")
        qapp.quit()

    # tray presence + clean quit (no Task Manager needed)
    tray = make_tray(
        cfg.hotkey_combo,
        quit_app,
        on_settings=lambda: show_window(settings_window),
        on_diagnostics=lambda: show_window(diagnostics_window),
        on_recovery=lambda: (recovery_window.refresh(), show_window(recovery_window)),
    )  # keep ref alive
    ctrl.health_signal.connect(
        lambda state, detail: update_tray_status(tray, state, detail)
    )
    if not permissions.report().ready:
        onboarding.show()

    def warmup() -> None:
        final_state = "ready"
        final_detail = "Cmd+Shift+Space to dictate"
        if service_manager is not None:
            print("[run] connecting to local cleanup service...")
            health = service_manager.connect_or_start()
            service_state["value"] = health.state.value
            ctrl.health_signal.emit(health.state.value, health.detail)
            print(f"[run] cleanup service {health.state.value}: {health.detail}")
            if health.api_key:
                ctrl.cleaner.set_api_key(health.api_key)
            if health.state.value != "ready":
                final_state = "degraded"
                final_detail = "using direct local cleanup fallback"
        print("[run] warming local models in the background...")
        ctrl.warmup()
        ctrl.health_signal.emit(final_state, final_detail)
        print("[run] local models ready.")

    def power_event(event: str) -> None:
        ctrl.on_system_event(event)
        if event == "wake" and not smoke_exit_ms:
            threading.Thread(target=warmup, name="wake-warmup", daemon=True).start()

    power_monitor = MacPowerMonitor(power_event)
    power_monitor.start()

    if smoke_exit_ms:
        update_tray_status(tray, "smoke", "bundle imports and shell initialized")
        QTimer.singleShot(smoke_exit_ms, qapp.quit)
    else:
        threading.Thread(target=warmup, name="model-warmup", daemon=True).start()
    print(
        f"[run] app ready. Toggle with {cfg.hotkey_combo}. "
        "Models continue warming in the background; quit via tray or Ctrl+C."
    )
    try:
        return qapp.exec()
    finally:
        if listener is not None:
            listener.stop()
        power_monitor.stop()
        tray.hide()
        if service_manager is not None:
            service_manager.stop()


def install_autostart() -> int:
    from . import autostart

    path = autostart.install()
    print(f"[autostart] installed -> {path}")
    print("[autostart] whisperflow-local will launch (windowless) on next login.")
    return 0


def uninstall_autostart() -> int:
    from . import autostart

    if autostart.uninstall():
        print("[autostart] removed; will no longer launch on login.")
    else:
        print("[autostart] nothing to remove (was not installed).")
    return 0


def cleanup_server_command() -> int:
    from .service import build_unsloth_command

    cmd = build_unsloth_command(load_config().cleanup)

    print("Start the cleanup server in another terminal:")
    print("  " + " ".join(shlex.quote(part) for part in cmd))
    print()
    print("The app normally starts this service and stores its generated key in Keychain.")
    print("For manual service use, store the printed key with:")
    print("  python -m whisperflow_local set-cleanup-key")
    return 0


def set_cleanup_key() -> int:
    from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore

    secret = getpass.getpass("Local cleanup server API key: ").strip()
    if not secret:
        print("[keychain] no key entered; nothing changed")
        return 1
    KeychainSecretStore().set(CLEANUP_API_KEY_ACCOUNT, secret)
    print("[keychain] cleanup server key stored for this macOS user")
    return 0


def delete_cleanup_key() -> int:
    from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore

    if KeychainSecretStore().delete(CLEANUP_API_KEY_ACCOUNT):
        print("[keychain] cleanup server key removed")
    else:
        print("[keychain] no stored cleanup server key")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "doctor":
        return doctor()
    if cmd == "selftest":
        return selftest()
    if cmd == "run":
        return run()
    if cmd == "install-autostart":
        return install_autostart()
    if cmd == "uninstall-autostart":
        return uninstall_autostart()
    if cmd == "cleanup-server-command":
        return cleanup_server_command()
    if cmd == "set-cleanup-key":
        return set_cleanup_key()
    if cmd == "delete-cleanup-key":
        return delete_cleanup_key()
    print(
        f"unknown command: {cmd}\nusage: python -m whisperflow_local "
        "[doctor|run|selftest|cleanup-server-command|set-cleanup-key|"
        "delete-cleanup-key|install-autostart|uninstall-autostart]"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
