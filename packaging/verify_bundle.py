from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path

EXPECTED_BUNDLE_ID = "com.shawnvanbrunt.whisperflow-local"
COMMAND_TIMEOUT_S = 30.0
SMOKE_EXIT_MS = 750
SMOKE_TIMEOUT_S = 15.0


def command_failure(
    *args: str, timeout: float = COMMAND_TIMEOUT_S
) -> str | None:
    try:
        result = subprocess.run(
            args, text=True, capture_output=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout:g}s"
    except OSError as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout).strip().splitlines()
    return detail[-1] if detail else f"exit {result.returncode}"


def smoke_launch_failure(executable: Path) -> str | None:
    """Launch the frozen app through its bounded, non-model smoke seam."""
    try:
        with tempfile.TemporaryDirectory(
            prefix="whisperflow-bundle-smoke-"
        ) as temp:
            home = Path(temp)
            temp_dir = home / "tmp"
            temp_dir.mkdir(mode=0o700)
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "CFFIXED_USER_HOME": str(home),
                "TMPDIR": str(temp_dir),
                "WHISPERFLOW_SMOKE_EXIT_MS": str(SMOKE_EXIT_MS),
                # Prevent smoke construction from consulting the real Keychain.
                "UNSLOTH_API_KEY": "whisperflow-smoke-isolated",
            })
            result = subprocess.run(
                [str(executable)],
                cwd=executable.parent,
                env=env,
                stdin=subprocess.DEVNULL,
                text=True,
                capture_output=True,
                check=False,
                timeout=SMOKE_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired:
        return f"timed out after {SMOKE_TIMEOUT_S:g}s"
    except OSError as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout).strip().splitlines()
    return detail[-1] if detail else f"exit {result.returncode}"


def verify_bundle(bundle: Path) -> list[str]:
    bundle = bundle.resolve()
    failures: list[str] = []
    info_path = bundle / "Contents" / "Info.plist"
    executable_dir = bundle / "Contents" / "MacOS"
    if not info_path.is_file():
        return ["Info.plist missing"]
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError, TypeError) as exc:
        return [f"Info.plist invalid: {type(exc).__name__}"]
    if not isinstance(info, dict):
        return ["Info.plist invalid: root is not a dictionary"]
    checks = {
        "CFBundleIdentifier": EXPECTED_BUNDLE_ID,
        "LSUIElement": True,
        "LSMultipleInstancesProhibited": True,
    }
    for key, expected in checks.items():
        if info.get(key) != expected:
            failures.append(f"{key}={info.get(key)!r}; expected {expected!r}")
    microphone = str(info.get("NSMicrophoneUsageDescription") or "")
    if "microphone" not in microphone.lower() or "locally" not in microphone.lower():
        failures.append("NSMicrophoneUsageDescription missing local-use explanation")
    executable_name = info.get("CFBundleExecutable")
    if not executable_name or not (executable_dir / executable_name).is_file():
        failures.append("bundle executable missing")
    elif not os.access(executable_dir / executable_name, os.X_OK):
        failures.append("bundle executable is not executable")
    if not (executable_dir / "config.yaml").is_file():
        failures.append("bundled config.yaml missing")
    if not (executable_dir / "assets" / "icon.png").is_file():
        failures.append("bundled icon missing")
    if not (executable_dir / "samples" / "test.wav").is_file():
        failures.append("bundled offline selftest sample missing")
    if not (executable_dir / "mlx.metallib").is_file():
        failures.append("bundled MLX Metal shader library missing")
    if not (
        executable_dir / "lightning_whisper_mlx" / "assets" / "mel_filters.npz"
    ).is_file():
        failures.append("bundled speech mel filterbank missing")
    signature_error = command_failure(
        "/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)
    )
    if signature_error:
        failures.append(f"invalid code signature: {signature_error}")
    try:
        requirement = subprocess.run(
            ["/usr/bin/codesign", "-d", "-r-", str(bundle)],
            text=True, capture_output=True, check=False,
            timeout=COMMAND_TIMEOUT_S,
        )
        requirement_text = requirement.stderr + requirement.stdout
    except (OSError, subprocess.TimeoutExpired):
        requirement_text = ""
    if f'designated => identifier "{EXPECTED_BUNDLE_ID}"' not in requirement_text:
        failures.append("stable designated code requirement missing")
    executable = executable_dir / str(executable_name or "")
    if executable.is_file():
        try:
            file_result = subprocess.run(
                ["/usr/bin/file", str(executable)], text=True,
                capture_output=True, check=False, timeout=COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            file_result = None
        if file_result is None or file_result.returncode or "arm64" not in file_result.stdout:
            failures.append("bundle executable is not arm64")
    if not failures:
        smoke_error = smoke_launch_failure(executable)
        if smoke_error:
            failures.append(f"bundle smoke launch failed: {smoke_error}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the local macOS app bundle")
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    failures = verify_bundle(args.bundle)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"PASS {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
