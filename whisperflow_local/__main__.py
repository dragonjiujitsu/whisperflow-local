"""CLI entrypoint: doctor | run | selftest."""
from __future__ import annotations

import importlib.util
import os
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


def _permission_health(report) -> tuple[str, str]:
    if report.ready:
        return "ready", "Cmd+Shift+Space to dictate"
    missing = []
    if report.microphone.value != "authorized":
        missing.append("Microphone")
    if report.accessibility.value != "authorized":
        missing.append("Accessibility")
    return "blocked", f"Grant {' and '.join(missing)} permission to dictate"


class _PermissionGate:
    """Activate the global listener only after both required TCC grants exist."""

    def __init__(self, listener, on_revoked=None) -> None:
        self._listener = listener
        self._on_revoked = on_revoked
        self._started = False
        self._was_ready = False
        self._lock = threading.Lock()

    def refresh(self, report) -> bool:
        revoked = False
        with self._lock:
            if not report.ready:
                revoked = self._was_ready
                self._was_ready = False
                if self._listener is not None and self._started:
                    self._listener.stop()
                    self._started = False
            else:
                if self._listener is not None and not self._started:
                    self._listener.start()
                    self._started = True
                self._was_ready = True
        if revoked and self._on_revoked is not None:
            self._on_revoked()
        return report.ready

    def stop(self) -> None:
        with self._lock:
            if self._listener is not None and self._started:
                self._listener.stop()
                self._started = False


class _EscapeKeyListener:
    """Global Escape cancellation, activated behind the permission gate."""

    def __init__(self, on_escape) -> None:
        self._on_escape = on_escape
        self._listener = None

    def start(self) -> None:
        if self._listener is not None:
            return
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=lambda key: (
                self._on_escape() if key == keyboard.Key.esc else None
            )
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class _ListenerGroup:
    def __init__(self, *listeners) -> None:
        self._listeners = listeners

    def start(self) -> None:
        started = []
        for listener in self._listeners:
            try:
                listener.start()
            except Exception:
                listener.stop()
                for active in reversed(started):
                    active.stop()
                raise
            started.append(listener)

    def stop(self) -> None:
        for listener in reversed(self._listeners):
            listener.stop()


class _WarmupFlight:
    """Run at most one initial/wake warmup flight at a time."""

    def __init__(self, target) -> None:
        self._target = target
        self._lock = threading.Lock()
        self._active = False
        self._thread: threading.Thread | None = None

    def start(self, name: str) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._thread = threading.Thread(
                target=self._run, name=name, daemon=True
            )
            self._thread.start()
            return True

    def _run(self) -> None:
        try:
            self._target()
        finally:
            with self._lock:
                self._active = False

    def wait(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()


def _warm_runtime(ctrl, service_manager, service_state) -> tuple[str, str]:
    final_state = "ready"
    final_detail = "Cmd+Shift+Space to dictate"
    if service_manager is not None:
        try:
            health = service_manager.connect_or_start()
            service_state["value"] = health.state.value
            print(f"[run] cleanup service {health.state.value}: {health.detail}")
            if (
                health.state.value == "ready"
                and health.owned
                and health.api_key
            ):
                ctrl.cleaner.set_api_key(health.api_key)
            elif health.state.value == "ready":
                final_state = "error"
                final_detail = "cleanup service ownership could not be verified"
            else:
                final_state = "degraded"
                final_detail = "cleanup unavailable; raw text will be recovered"
        except Exception as exc:
            service_state["value"] = "error"
            final_state = "error"
            final_detail = f"cleanup startup failed: {type(exc).__name__}"
    try:
        ctrl.warmup()
    except Exception as exc:
        return "error", f"model warmup failed: {type(exc).__name__}"
    return final_state, final_detail


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
def _cleanup_doctor_checks(cleanup: dict) -> list[tuple[str, bool, str]]:
    provider = str(cleanup.get("provider", "ollama")).lower()
    want = str(cleanup["model"])
    if provider == "unsloth-cli":
        return [(
            "unsloth-cli",
            False,
            "disabled because the CLI exposes prompt data in process arguments",
        )]
    if provider == "ollama":
        try:
            from .cleanup import validate_ollama_host

            host = validate_ollama_host(os.environ.get("OLLAMA_HOST", ""))
            return [(
                "ollama",
                True,
                f"loopback configured at {host}; model {want}; runtime not probed",
            )]
        except Exception as exc:
            return [("ollama", False, str(exc))]
    if provider in {"openai-compatible", "omlx"}:
        try:
            from .local_endpoint import validate_loopback_http_url
            from .model_manager import ModelManager, ModelState

            base_url = validate_loopback_http_url(
                str(cleanup.get("base_url", "http://localhost:8888/v1"))
            )
            model = ModelManager().resolve_gguf(
                str(cleanup.get("server_model") or ""),
                str(cleanup.get("server_gguf_variant") or ""),
                str(cleanup.get("model_path") or ""),
            )
            present = model.state is ModelState.READY
            detail = (
                f"app-owned endpoint configured at {base_url}; "
                f"local model {model.state.value}"
            )
            return [(provider, present, detail)]
        except Exception as exc:
            return [(provider, False, str(exc))]
    return [("cleanup-provider", False, f"unsupported provider {provider!r}")]


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

    checks.extend(_cleanup_doctor_checks(cfg.cleanup))

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
def _run_owned_cleanup_selftest(cleaner, transcript: str, service_manager) -> str:
    """Clean self-test text only through a READY child owned by this process."""
    health = service_manager.connect_or_start()
    if (
        health.state.value != "ready"
        or not health.owned
        or not health.api_key
    ):
        raise RuntimeError("selftest cleanup requires a READY app-owned service")
    cleaner.set_api_key(health.api_key)
    return cleaner.clean(transcript)


def selftest() -> int:
    cfg = load_config()
    results: dict[str, bool] = {}

    results["1_sample"] = ensure_sample()
    if not results["1_sample"]:
        return _report(results)

    audio, sr = load_wav_16k_mono(SAMPLE)

    # STT
    from .app import _resolved_stt_config
    from .stt import Transcriber

    stt = Transcriber(_resolved_stt_config(cfg))
    transcript = stt.transcribe(audio, sr)
    print(f"[stt] {transcript!r}")
    results["2_stt_nonempty"] = bool(transcript.strip())

    # Managed OpenAI-compatible cleanup must only use a child started and
    # authenticated by this process. Ollama is supported separately because
    # Cleaner pins its client to a validated HTTP loopback endpoint.
    from .cleanup import Cleaner

    provider = str(cfg.cleanup.get("provider", "")).lower()
    if provider not in {"ollama", "openai-compatible", "omlx"}:
        print("[cleanup] selftest cleanup provider is unsupported")
        results["3_cleanup_nonempty"] = False
        results["3b_filler_reduced"] = False
        return _report(results)

    cleaner = Cleaner(cfg.cleanup)
    if provider == "ollama":
        try:
            cleaned = cleaner.clean(transcript)
        except Exception as exc:
            print(f"[cleanup] unavailable: {type(exc).__name__}")
            results["3_cleanup_nonempty"] = False
            results["3b_filler_reduced"] = False
            return _report(results)
    else:
        from .service import LocalServiceManager

        service_manager = LocalServiceManager(cfg.cleanup)
        try:
            cleaned = _run_owned_cleanup_selftest(
                cleaner, transcript, service_manager
            )
        except Exception as exc:
            print(f"[cleanup] unavailable: {type(exc).__name__}")
            results["3_cleanup_nonempty"] = False
            results["3b_filler_reduced"] = False
            return _report(results)
        finally:
            service_manager.stop()
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
        listener = _ListenerGroup(
            HotkeyListener(cfg.hotkey_combo, ctrl.on_hotkey),
            _EscapeKeyListener(ctrl.cancel_requested.emit),
        )

    permissions = MacPermissions()
    permission_gate = _PermissionGate(
        listener,
        on_revoked=lambda: ctrl.on_system_event("permissions_revoked"),
    )
    model_manager = ModelManager()
    onboarding = OnboardingWindow(permissions)
    settings_window = SettingsWindow(REPO / "config.yaml")
    recovery_window = RecoveryWindow(ctrl.recovery, ctrl.history)
    service_state = {"value": "starting" if service_manager else "fallback"}
    warmup_state = {
        "complete": False,
        "state": "warming",
        "detail": "warming local models",
    }

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
    initial_permissions = permissions.report()
    permission_gate.refresh(initial_permissions)
    if not initial_permissions.ready:
        onboarding.show()
        ctrl.health_signal.emit(*_permission_health(initial_permissions))

    last_runtime_health = {"value": None}

    def publish_runtime_health(report=None) -> bool:
        report = report or permissions.report()
        if not permission_gate.refresh(report):
            health = _permission_health(report)
        elif warmup_state["complete"]:
            health = (
                str(warmup_state["state"]), str(warmup_state["detail"])
            )
        else:
            return True
        if health != last_runtime_health["value"]:
            last_runtime_health["value"] = health
            ctrl.health_signal.emit(*health)
        return report.ready

    def refresh_permissions() -> None:
        report = permissions.report()
        if publish_runtime_health(report) and onboarding.isVisible():
            onboarding.hide()

    permission_refresh_timer = QTimer(qapp)
    permission_refresh_timer.setInterval(1000)
    permission_refresh_timer.timeout.connect(refresh_permissions)
    permission_refresh_timer.start()

    def warmup() -> None:
        warmup_state["complete"] = False
        if service_manager is not None:
            print("[run] connecting to local cleanup service...")
        print("[run] warming local models in the background...")
        final_state, final_detail = _warm_runtime(
            ctrl, service_manager, service_state
        )
        warmup_state.update(
            complete=True, state=final_state, detail=final_detail
        )
        publish_runtime_health()
        print(f"[run] warmup {final_state}: {final_detail}")

    warmup_flight = _WarmupFlight(warmup)

    def power_event(event: str) -> None:
        ctrl.on_system_event(event)
        if event == "wake" and not smoke_exit_ms:
            warmup_flight.start("wake-warmup")

    power_monitor = MacPowerMonitor(power_event)
    power_monitor.start()

    if smoke_exit_ms:
        update_tray_status(tray, "smoke", "bundle imports and shell initialized")
        QTimer.singleShot(smoke_exit_ms, qapp.quit)
    else:
        warmup_flight.start("model-warmup")
    print(
        f"[run] app launched. Toggle with {cfg.hotkey_combo} when ready. "
        "Models continue warming in the background; quit via tray or Ctrl+C."
    )
    try:
        return qapp.exec()
    finally:
        permission_gate.stop()
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
    if cmd == "delete-cleanup-key":
        return delete_cleanup_key()
    print(
        f"unknown command: {cmd}\nusage: python -m whisperflow_local "
        "[doctor|run|selftest|delete-cleanup-key|"
        "install-autostart|uninstall-autostart]"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
