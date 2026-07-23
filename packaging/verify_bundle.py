from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path

EXPECTED_BUNDLE_ID = "com.shawnvanbrunt.whisperflow-local"


def command_failure(*args: str) -> str | None:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout).strip().splitlines()
    return detail[-1] if detail else f"exit {result.returncode}"


def verify_bundle(bundle: Path) -> list[str]:
    failures: list[str] = []
    info_path = bundle / "Contents" / "Info.plist"
    executable_dir = bundle / "Contents" / "MacOS"
    if not info_path.is_file():
        return ["Info.plist missing"]
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
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
    requirement = subprocess.run(
        ["/usr/bin/codesign", "-d", "-r-", str(bundle)],
        text=True, capture_output=True, check=False,
    )
    requirement_text = requirement.stderr + requirement.stdout
    if f'designated => identifier "{EXPECTED_BUNDLE_ID}"' not in requirement_text:
        failures.append("stable designated code requirement missing")
    executable = executable_dir / str(executable_name or "")
    if executable.is_file():
        file_result = subprocess.run(
            ["/usr/bin/file", str(executable)], text=True, capture_output=True, check=False
        )
        if file_result.returncode or "arm64" not in file_result.stdout:
            failures.append("bundle executable is not arm64")
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
