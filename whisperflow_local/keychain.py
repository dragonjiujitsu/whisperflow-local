"""Minimal macOS Keychain secret store using the system security tool."""
from __future__ import annotations

import subprocess

from .paths import BUNDLE_ID

CLEANUP_API_KEY_ACCOUNT = "cleanup-api-key"


class KeychainSecretStore:
    def __init__(self, service: str = BUNDLE_ID) -> None:
        self.service = service

    def get(self, account: str) -> str:
        proc = subprocess.run(
            [
                "security", "find-generic-password", "-s", self.service,
                "-a", account, "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout.rstrip("\n")

    def set(self, account: str, secret: str) -> None:
        if not secret:
            raise ValueError("secret must not be empty")
        # Do not log or return the command: argv contains the secret briefly.
        subprocess.run(
            [
                "security", "add-generic-password", "-U", "-s", self.service,
                "-a", account, "-w", secret,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )

    def delete(self, account: str) -> bool:
        proc = subprocess.run(
            [
                "security", "delete-generic-password", "-s", self.service,
                "-a", account,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return proc.returncode == 0
