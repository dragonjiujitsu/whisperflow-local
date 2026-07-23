from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / ".build" / "WhisperFlow Local.app"
DEFAULT_INSTALL = Path("/Applications/WhisperFlow Local.app")


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def normalize_resource_permissions(bundle: Path) -> None:
    """Keep non-code resources from being treated as executable code slots."""
    macos = bundle / "Contents" / "MacOS"
    for relative in (Path("config.yaml"), Path("assets")):
        target = macos / relative
        paths = target.rglob("*") if target.is_dir() else (target,)
        for path in paths:
            if path.is_file():
                path.chmod(path.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def install_mlx_metallib(bundle: Path) -> None:
    distribution = importlib.metadata.distribution("mlx")
    source = Path(distribution.locate_file("mlx/lib/mlx.metallib"))
    if not source.is_file():
        raise RuntimeError(f"MLX Metal shader library missing: {source}")
    destination = bundle / "Contents" / "MacOS" / "mlx.metallib"
    shutil.copy2(source, destination)
    destination.chmod(destination.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify WhisperFlow Local.app")
    parser.add_argument("--skip-deploy", action="store_true", help="sign/verify an existing bundle")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument(
        "--install", action="store_true",
        help="replace /Applications/WhisperFlow Local.app with the verified bundle",
    )
    args = parser.parse_args()
    bundle = args.bundle.resolve()

    if not args.skip_deploy:
        deploy = ROOT / ".venv" / "bin" / "pyside6-deploy"
        run(str(deploy), "-c", "pysidedeploy.spec", "-f")
    if not bundle.is_dir():
        parser.error(f"bundle not found: {bundle}")

    install_mlx_metallib(bundle)
    normalize_resource_permissions(bundle)
    # Qt deployment can modify a bundle after Nuitka signs its emitted code.
    # The final recursive signature must therefore be the last mutation.
    identity = os.environ.get("WHISPERFLOW_CODESIGN_IDENTITY", "-")
    run(
        "/usr/bin/codesign", "--force", "--deep", "--sign", identity,
        "--timestamp=none", str(bundle),
    )
    # Apply the persistent identity only to the outer app. Giving this
    # requirement to nested frameworks invalidates their distinct identifiers.
    run(
        "/usr/bin/codesign", "--force", "--sign", identity,
        "--requirements",
        '=designated => identifier "com.shawnvanbrunt.whisperflow-local"',
        "--timestamp=none", str(bundle),
    )
    run(sys.executable, "packaging/verify_bundle.py", str(bundle))
    if args.install:
        if DEFAULT_INSTALL.exists():
            shutil.rmtree(DEFAULT_INSTALL)
        # Preserve the extended signature metadata Nuitka/codesign attaches to
        # nested bundle resources. shutil.copytree drops these code-signing
        # xattrs and leaves an app that looks intact but fails strict validation.
        run(
            "/usr/bin/ditto", "--rsrc", "--extattr",
            str(bundle), str(DEFAULT_INSTALL),
        )
        run(sys.executable, "packaging/verify_bundle.py", str(DEFAULT_INSTALL))
        print(f"Installed: {DEFAULT_INSTALL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
