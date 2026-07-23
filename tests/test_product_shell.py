from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


class ProductShellTests(unittest.TestCase):
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
