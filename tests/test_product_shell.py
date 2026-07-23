from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whisperflow_local.diagnostics import build_diagnostics
from whisperflow_local.model_manager import ModelHealth, ModelState
from whisperflow_local.onboarding import (
    permission_button_state, permission_message, python_completion_handler,
    status_card_style,
)
from whisperflow_local.paths import AppPaths
from whisperflow_local.platform.macos.permissions import (
    PermissionReport,
    PermissionStatus,
)
from whisperflow_local.__main__ import (
    _ListenerGroup,
    _PermissionGate,
    _cleanup_doctor_checks,
    _permission_health,
    _run_owned_cleanup_selftest,
    selftest,
)
from whisperflow_local.app import PROCESSING, Controller
from whisperflow_local.session import SessionEvent, SessionPhase, SessionReducer


class ProductShellTests(unittest.TestCase):
    def test_selftest_uses_resolved_performance_profile_for_stt(self) -> None:
        cfg = SimpleNamespace(
            stt={"model": "stale-config", "batch_size": 1},
            performance={"profile": "quality"},
        )
        transcriber = Mock()
        transcriber.transcribe.side_effect = RuntimeError("stop after STT")

        with patch(
            "whisperflow_local.__main__.load_config", return_value=cfg
        ), patch(
            "whisperflow_local.__main__.ensure_sample", return_value=True
        ), patch(
            "whisperflow_local.__main__.load_wav_16k_mono",
            return_value=(object(), 16000),
        ), patch(
            "whisperflow_local.app._resolved_stt_config",
            return_value={"model": "large-v3", "batch_size": 8},
        ) as resolve_stt, patch(
            "whisperflow_local.stt.Transcriber", return_value=transcriber
        ) as transcriber_type:
            with self.assertRaisesRegex(RuntimeError, "stop after STT"):
                selftest()

        resolve_stt.assert_called_once_with(cfg)
        transcriber_type.assert_called_once_with(
            {"model": "large-v3", "batch_size": 8}
        )

    def test_selftest_uses_validated_ollama_cleaner_without_service_manager(
        self,
    ) -> None:
        cfg = SimpleNamespace(
            stt={},
            performance={"profile": "instant"},
            cleanup={"provider": "ollama"},
            insert={},
        )
        transcriber = Mock()
        transcriber.transcribe.return_value = "um hello"
        cleaner = Mock()
        cleaner.clean.return_value = "hello"

        with patch(
            "whisperflow_local.__main__.load_config", return_value=cfg
        ), patch(
            "whisperflow_local.__main__.ensure_sample", return_value=True
        ), patch(
            "whisperflow_local.__main__.load_wav_16k_mono",
            return_value=(object(), 16000),
        ), patch(
            "whisperflow_local.app._resolved_stt_config", return_value={}
        ), patch(
            "whisperflow_local.stt.Transcriber", return_value=transcriber
        ), patch(
            "whisperflow_local.cleanup.Cleaner", return_value=cleaner
        ), patch(
            "whisperflow_local.service.LocalServiceManager"
        ) as service_manager, patch(
            "whisperflow_local.inserter.Inserter"
        ), patch(
            "whisperflow_local.__main__._prepare_textedit_selftest_target",
            return_value=False,
        ):
            self.assertEqual(selftest(), 1)

        cleaner.clean.assert_called_once_with("um hello")
        service_manager.assert_not_called()

    def test_selftest_rejects_unsupported_cleanup_before_construction(self) -> None:
        cfg = SimpleNamespace(
            stt={},
            performance={"profile": "instant"},
            cleanup={"provider": "unsupported"},
        )
        transcriber = Mock()
        transcriber.transcribe.return_value = "private transcript"

        with patch(
            "whisperflow_local.__main__.load_config", return_value=cfg
        ), patch(
            "whisperflow_local.__main__.ensure_sample", return_value=True
        ), patch(
            "whisperflow_local.__main__.load_wav_16k_mono",
            return_value=(object(), 16000),
        ), patch(
            "whisperflow_local.app._resolved_stt_config", return_value={}
        ), patch(
            "whisperflow_local.stt.Transcriber", return_value=transcriber
        ), patch(
            "whisperflow_local.cleanup.Cleaner"
        ) as cleaner_type, patch(
            "whisperflow_local.service.LocalServiceManager"
        ) as service_manager:
            self.assertEqual(selftest(), 1)

        cleaner_type.assert_not_called()
        service_manager.assert_not_called()

    def test_listener_group_rolls_back_partial_start(self) -> None:
        events = []

        class Listener:
            def __init__(self, name, fail=False):
                self.name = name
                self.fail = fail

            def start(self):
                events.append(f"start:{self.name}")
                if self.fail:
                    raise RuntimeError("registration failed")

            def stop(self):
                events.append(f"stop:{self.name}")

        group = _ListenerGroup(Listener("hotkey"), Listener("escape", fail=True))
        with self.assertRaisesRegex(RuntimeError, "registration failed"):
            group.start()
        self.assertEqual(
            events,
            [
                "start:hotkey",
                "start:escape",
                "stop:escape",
                "stop:hotkey",
            ],
        )

    def test_permission_revocation_deactivates_global_listeners(self) -> None:
        class Listener:
            def __init__(self):
                self.starts = 0
                self.stops = 0

            def start(self):
                self.starts += 1

            def stop(self):
                self.stops += 1

        listener = Listener()
        gate = _PermissionGate(listener)
        ready = PermissionReport(
            PermissionStatus.AUTHORIZED, PermissionStatus.AUTHORIZED
        )
        revoked = PermissionReport(
            PermissionStatus.AUTHORIZED, PermissionStatus.DENIED
        )

        self.assertTrue(gate.refresh(ready))
        self.assertFalse(gate.refresh(revoked))
        self.assertEqual((listener.starts, listener.stops), (1, 1))

    def test_permission_revocation_invokes_session_cancellation(self) -> None:
        listener = type(
            "Listener", (), {"start": lambda self: None, "stop": lambda self: None}
        )()
        sessions = SessionReducer()
        session = sessions.start()
        for event in (
            SessionEvent.RECORDING_STARTED,
            SessionEvent.RECORDING_STOPPED,
            SessionEvent.TRANSCRIPTION_STARTED,
        ):
            sessions.transition(session.session_id, event)
        controller = SimpleNamespace(
            state=PROCESSING,
            sessions=sessions,
            health_signal=Mock(),
            log=Mock(),
        )
        gate = _PermissionGate(
            listener,
            on_revoked=lambda: Controller._on_interrupt(
                controller, "permissions_revoked"
            ),
        )
        ready = PermissionReport(
            PermissionStatus.AUTHORIZED, PermissionStatus.AUTHORIZED
        )
        denied = PermissionReport(
            PermissionStatus.AUTHORIZED, PermissionStatus.DENIED
        )

        gate.refresh(ready)
        gate.refresh(denied)

        self.assertEqual(sessions.current.phase, SessionPhase.CANCELLED)
        self.assertTrue(session.cancelled.is_set())

    def test_doctor_does_not_probe_unowned_authenticated_service(self) -> None:
        cleanup = {
            "provider": "openai-compatible",
            "base_url": "http://localhost:8888/v1",
            "model": "default",
            "model_path": "/definitely/missing.gguf",
            "server_model": "unsloth/example",
            "server_gguf_variant": "Q4",
        }
        with patch(
            "whisperflow_local.keychain.KeychainSecretStore.get"
        ) as keychain_get, patch(
            "whisperflow_local.local_endpoint.open_local_request"
        ) as open_request:
            checks = _cleanup_doctor_checks(cleanup)

        keychain_get.assert_not_called()
        open_request.assert_not_called()
        self.assertEqual(checks[0][0], "openai-compatible")
        self.assertIn("app-owned", checks[0][2])

    def test_doctor_does_not_probe_unowned_ollama_listener(self) -> None:
        cleanup = {"provider": "ollama", "model": "qwen"}
        with patch("ollama.Client") as client:
            checks = _cleanup_doctor_checks(cleanup)

        client.assert_not_called()
        self.assertEqual(checks[0][0], "ollama")
        self.assertIn("not probed", checks[0][2])

    def test_selftest_injects_only_ready_owned_service_key(self) -> None:
        cleaner = Mock()
        cleaner.clean.return_value = "cleaned"
        manager = Mock()
        manager.connect_or_start.return_value = SimpleNamespace(
            state=SimpleNamespace(value="ready"),
            owned=True,
            api_key="runtime-key",
            detail="app-owned local service ready",
        )

        cleaned = _run_owned_cleanup_selftest(cleaner, "raw", manager)

        cleaner.set_api_key.assert_called_once_with("runtime-key")
        cleaner.clean.assert_called_once_with("raw")
        self.assertEqual(cleaned, "cleaned")

    def test_selftest_refuses_unowned_listener_without_sending_transcript(self) -> None:
        cleaner = Mock()
        manager = Mock()
        manager.connect_or_start.return_value = SimpleNamespace(
            state=SimpleNamespace(value="error"),
            owned=False,
            api_key="",
            detail="refusing pre-existing listener",
        )

        with self.assertRaisesRegex(RuntimeError, "READY app-owned"):
            _run_owned_cleanup_selftest(cleaner, "private transcript", manager)

        cleaner.set_api_key.assert_not_called()
        cleaner.clean.assert_not_called()

    def test_missing_permissions_block_runtime_readiness(self) -> None:
        state, detail = _permission_health(
            PermissionReport(PermissionStatus.AUTHORIZED, PermissionStatus.DENIED)
        )
        self.assertEqual(state, "blocked")
        self.assertIn("Accessibility", detail)

    def test_all_permissions_allow_runtime_readiness(self) -> None:
        state, detail = _permission_health(
            PermissionReport(
                PermissionStatus.AUTHORIZED, PermissionStatus.AUTHORIZED
            )
        )
        self.assertEqual(state, "ready")
        self.assertIn("dictate", detail)

    def test_permission_copy_is_actionable_and_distinct(self) -> None:
        self.assertEqual(
            permission_message("Microphone", PermissionStatus.AUTHORIZED),
            "Microphone: Ready",
        )
        self.assertIn(
            "not requested",
            permission_message("Microphone", PermissionStatus.NOT_DETERMINED),
        )
        self.assertIn(
            "denied",
            permission_message("Accessibility", PermissionStatus.DENIED),
        )

    def test_permission_cards_have_explicit_dark_mode_safe_contrast(self) -> None:
        for status in PermissionStatus:
            style = status_card_style(status)
            self.assertIn("color:", style)
            self.assertIn("background-color:", style)

    def test_microphone_completion_bridge_is_a_plain_python_function(self) -> None:
        values = []
        completion = python_completion_handler(values.append)
        self.assertEqual(type(completion).__name__, "function")
        completion(1)
        self.assertEqual(values, [True])

    def test_permission_buttons_reflect_current_tcc_state(self) -> None:
        self.assertEqual(
            permission_button_state("Accessibility", PermissionStatus.AUTHORIZED),
            ("Accessibility Ready", False),
        )
        self.assertEqual(
            permission_button_state("Accessibility", PermissionStatus.DENIED),
            ("Open Accessibility Settings", True),
        )

    def test_diagnostics_contains_health_but_no_content_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = build_diagnostics(
                PermissionReport(
                    PermissionStatus.AUTHORIZED, PermissionStatus.DENIED
                ),
                ModelHealth(ModelState.READY, Path("/private/model.gguf")),
                "degraded",
                AppPaths.discover(Path(temp)),
            )
        rendered = repr(report).lower()
        self.assertIn("permissions", report)
        self.assertIn("model", report)
        self.assertNotIn("/private/model.gguf", rendered)
        for forbidden in (
            "transcript", "cleaned_text", "audio_data", "api_key", "secret"
        ):
            self.assertNotIn(forbidden, rendered)

    def test_diagnostics_reports_presence_not_settings_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp)).ensure()
            paths.settings.write_text("private-value")
            report = build_diagnostics(
                PermissionReport(
                    PermissionStatus.AUTHORIZED, PermissionStatus.AUTHORIZED
                ),
                ModelHealth(ModelState.MISSING, detail="not installed"),
                "stopped",
                paths,
            )
        self.assertTrue(report["settings_present"])
        self.assertNotIn("private-value", repr(report))


if __name__ == "__main__":
    unittest.main()
