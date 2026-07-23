from __future__ import annotations

import os
import plistlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "packaging" / "verify_bundle.py"
SPEC = importlib.util.spec_from_file_location("whisperflow_verify_bundle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFY_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_MODULE)
EXPECTED_BUNDLE_ID = VERIFY_MODULE.EXPECTED_BUNDLE_ID
verify_bundle = VERIFY_MODULE.verify_bundle
smoke_launch_failure = VERIFY_MODULE.smoke_launch_failure


def completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class VerifyBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = []

    def make_bundle(self, root: Path) -> Path:
        bundle = root / "WhisperFlow Local.app"
        executable_dir = bundle / "Contents" / "MacOS"
        (executable_dir / "assets").mkdir(parents=True)
        (executable_dir / "samples").mkdir()
        (executable_dir / "lightning_whisper_mlx" / "assets").mkdir(parents=True)
        info = {
            "CFBundleIdentifier": EXPECTED_BUNDLE_ID,
            "CFBundleExecutable": "whisperflow-local",
            "LSUIElement": True,
            "LSMultipleInstancesProhibited": True,
            "NSMicrophoneUsageDescription": "Uses the microphone locally.",
        }
        with (bundle / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump(info, handle)
        for relative in (
            "whisperflow-local", "config.yaml", "assets/icon.png",
            "samples/test.wav", "mlx.metallib",
            "lightning_whisper_mlx/assets/mel_filters.npz",
        ):
            path = executable_dir / relative
            path.write_bytes(b"fixture")
        os.chmod(executable_dir / "whisperflow-local", 0o755)
        return bundle

    def successful_command(self, args, **kwargs):
        argv = tuple(args)
        self.commands.append(argv)
        if argv[:4] == (
            "/usr/bin/codesign", "--verify", "--deep", "--strict"
        ):
            self.assertEqual(kwargs["timeout"], VERIFY_MODULE.COMMAND_TIMEOUT_S)
            return completed()
        if argv[:3] == ("/usr/bin/codesign", "-d", "-r-"):
            self.assertEqual(kwargs["timeout"], VERIFY_MODULE.COMMAND_TIMEOUT_S)
            return completed(
                stderr=f'designated => identifier "{EXPECTED_BUNDLE_ID}" and anchor apple generic'
            )
        if argv[:1] == ("/usr/bin/file",):
            self.assertEqual(kwargs["timeout"], VERIFY_MODULE.COMMAND_TIMEOUT_S)
            return completed(stdout="Mach-O 64-bit executable arm64")
        if len(argv) == 1 and argv[0].endswith("/whisperflow-local"):
            env = kwargs["env"]
            self.assertEqual(
                env["WHISPERFLOW_SMOKE_EXIT_MS"],
                str(VERIFY_MODULE.SMOKE_EXIT_MS),
            )
            self.assertEqual(env["HOME"], env["CFFIXED_USER_HOME"])
            self.assertNotEqual(Path(env["HOME"]), Path.home())
            self.assertEqual(env["UNSLOTH_API_KEY"], "whisperflow-smoke-isolated")
            self.assertEqual(kwargs["timeout"], VERIFY_MODULE.SMOKE_TIMEOUT_S)
            self.assertEqual(Path(kwargs["cwd"]), Path(argv[0]).parent)
            return completed()
        raise AssertionError(f"unexpected command: {argv!r}")

    def test_accepts_complete_signed_arm64_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(
            VERIFY_MODULE.subprocess, "run", side_effect=self.successful_command
        ):
            bundle = self.make_bundle(Path(temp)).resolve()
            self.assertEqual(verify_bundle(bundle), [])
        executable = str(bundle / "Contents" / "MacOS" / "whisperflow-local")
        self.assertEqual(
            self.commands,
            [
                (
                    "/usr/bin/codesign", "--verify", "--deep", "--strict",
                    str(bundle),
                ),
                ("/usr/bin/codesign", "-d", "-r-", str(bundle)),
                ("/usr/bin/file", executable),
                (executable,),
            ],
        )

    def test_reports_malformed_plist_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "Broken.app"
            info = bundle / "Contents" / "Info.plist"
            info.parent.mkdir(parents=True)
            info.write_bytes(b"not a plist")
            failures = verify_bundle(bundle)
        self.assertTrue(any("Info.plist invalid" in item for item in failures))

    def test_rejects_non_executable_wrong_architecture_and_bad_signature(self) -> None:
        def failing_command(args, **kwargs):
            argv = tuple(args)
            if "--verify" in argv:
                return completed(1, stderr="code object is not signed")
            if argv[:3] == ("/usr/bin/codesign", "-d", "-r-"):
                return completed(1, stderr="not signed at all")
            return completed(stdout="Mach-O 64-bit executable x86_64")

        with tempfile.TemporaryDirectory() as temp, patch.object(
            VERIFY_MODULE.subprocess, "run", side_effect=failing_command
        ):
            bundle = self.make_bundle(Path(temp))
            os.chmod(bundle / "Contents" / "MacOS" / "whisperflow-local", 0o644)
            failures = verify_bundle(bundle)
        self.assertIn("bundle executable is not executable", failures)
        self.assertTrue(any("invalid code signature" in item for item in failures))
        self.assertIn("stable designated code requirement missing", failures)
        self.assertIn("bundle executable is not arm64", failures)

    def test_every_required_resource_has_a_rejection_branch(self) -> None:
        cases = {
            "config.yaml": "bundled config.yaml missing",
            "assets/icon.png": "bundled icon missing",
            "samples/test.wav": "bundled offline selftest sample missing",
            "mlx.metallib": "bundled MLX Metal shader library missing",
            "lightning_whisper_mlx/assets/mel_filters.npz":
                "bundled speech mel filterbank missing",
        }
        for relative, expected in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp:
                bundle = self.make_bundle(Path(temp))
                (bundle / "Contents" / "MacOS" / relative).unlink()
                self.commands = []
                with patch.object(
                    VERIFY_MODULE.subprocess, "run",
                    side_effect=self.successful_command,
                ):
                    failures = verify_bundle(bundle)
                self.assertIn(expected, failures)
                self.assertFalse(
                    any(
                        len(command) == 1
                        and command[0].endswith("/whisperflow-local")
                        for command in self.commands
                    )
                )

    def test_external_command_timeouts_fail_closed(self) -> None:
        cases = (
            ("signature", lambda argv: "--verify" in argv, "invalid code signature"),
            (
                "requirement",
                lambda argv: argv[:3] == ("/usr/bin/codesign", "-d", "-r-"),
                "stable designated code requirement missing",
            ),
            ("architecture", lambda argv: argv[:1] == ("/usr/bin/file",),
             "bundle executable is not arm64"),
            ("smoke", lambda argv: len(argv) == 1, "bundle smoke launch failed"),
        )
        for name, matches, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                bundle = self.make_bundle(Path(temp))

                def timed_command(args, **kwargs):
                    argv = tuple(args)
                    if matches(argv):
                        raise VERIFY_MODULE.subprocess.TimeoutExpired(
                            argv, kwargs["timeout"]
                        )
                    return self.successful_command(args, **kwargs)

                with patch.object(
                    VERIFY_MODULE.subprocess, "run", side_effect=timed_command
                ):
                    failures = verify_bundle(bundle)
                self.assertTrue(any(expected in failure for failure in failures))

    def test_smoke_launch_executes_with_isolated_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "smoke-app"
            executable.write_text(
                "#!/bin/sh\n"
                "test \"$HOME\" = \"$CFFIXED_USER_HOME\" || exit 11\n"
                f"test \"$WHISPERFLOW_SMOKE_EXIT_MS\" = \"{VERIFY_MODULE.SMOKE_EXIT_MS}\" || exit 12\n"
                "test \"$UNSLOTH_API_KEY\" = \"whisperflow-smoke-isolated\" || exit 13\n"
            )
            executable.chmod(0o755)
            self.assertIsNone(smoke_launch_failure(executable))


if __name__ == "__main__":
    unittest.main()
