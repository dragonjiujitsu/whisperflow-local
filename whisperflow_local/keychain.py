"""Minimal macOS Keychain secret store using the system security tool."""
from __future__ import annotations

import subprocess

from .paths import BUNDLE_ID

CLEANUP_API_KEY_ACCOUNT = "cleanup-api-key"


class KeychainSecretStore:
    def __init__(self, service: str = BUNDLE_ID, security=None) -> None:
        self.service = service
        self._security = security

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
        security = self._security or _SecurityFrameworkAdapter()
        security.set_generic_password(self.service, account, secret)

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


class _SecurityFrameworkAdapter:
    """Small in-process SecItem adapter loaded through the installed PyObjC core."""

    _ITEM_NOT_FOUND = -25300

    def __init__(self) -> None:
        import objc
        from Foundation import NSData, NSBundle

        bundle = NSBundle.bundleWithPath_(
            "/System/Library/Frameworks/Security.framework"
        )
        if bundle is None or not bundle.load():
            raise RuntimeError("unable to load macOS Security.framework")

        symbols: dict = {}
        objc.loadBundleVariables(bundle, symbols, [
            ("kSecClass", b"@"),
            ("kSecClassGenericPassword", b"@"),
            ("kSecAttrService", b"@"),
            ("kSecAttrAccount", b"@"),
            ("kSecValueData", b"@"),
        ])
        objc.loadBundleFunctions(bundle, symbols, [
            ("SecItemAdd", b"i@^@"),
            ("SecItemUpdate", b"i@@"),
        ])
        self._symbols = symbols
        self._data_type = NSData

    def set_generic_password(
        self, service: str, account: str, secret: str
    ) -> None:
        symbols = self._symbols
        query = {
            symbols["kSecClass"]: symbols["kSecClassGenericPassword"],
            symbols["kSecAttrService"]: service,
            symbols["kSecAttrAccount"]: account,
        }
        encoded = secret.encode("utf-8")
        value = self._data_type.dataWithBytes_length_(encoded, len(encoded))
        update = {symbols["kSecValueData"]: value}
        status = symbols["SecItemUpdate"](query, update)
        if status == self._ITEM_NOT_FOUND:
            status = symbols["SecItemAdd"](
                {**query, symbols["kSecValueData"]: value}, None
            )
        if status != 0:
            raise OSError(status, "unable to store secret in macOS Keychain")
