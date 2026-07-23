"""GUI bundle entry point with an explicit deterministic release-test seam."""
import os

from whisperflow_local.__main__ import run, selftest


if __name__ == "__main__":
    target = selftest if os.environ.get("WHISPERFLOW_BUNDLE_SELFTEST") == "1" else run
    raise SystemExit(target())
