"""Lifecycle for the warm localhost cleanup service."""
from __future__ import annotations

import json
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib import request
from urllib.parse import urlsplit

from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore
from .local_endpoint import open_local_request, validate_loopback_http_url

_KEY = re.compile(r"sk-unsloth-[A-Za-z0-9_-]+")


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class ServiceHealth:
    state: ServiceState
    owned: bool = False
    detail: str = ""
    api_key: str = ""


def resolve_unsloth_executable() -> str:
    """Resolve Unsloth now so child launch never performs a later PATH lookup."""
    found = shutil.which("unsloth")
    if found is None:
        raise RuntimeError("unsloth executable not found on PATH")
    return str(Path(found).resolve())


def build_unsloth_command(
    cleanup: dict, executable: str | None = None
) -> list[str]:
    base_url = validate_loopback_http_url(
        str(cleanup.get("base_url", "http://127.0.0.1:8888/v1"))
    )
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port)
    executable_path = Path(executable or resolve_unsloth_executable())
    if not executable_path.is_absolute():
        raise ValueError("unsloth executable must be an absolute path")
    resolved_executable = str(executable_path.resolve())
    command = [
        resolved_executable, "run", "--model",
        str(cleanup.get("server_model") or cleanup.get("model_path")),
        "--host", host,
        "--port", port,
        "--disable-tools",
    ]
    variant = str(cleanup.get("server_gguf_variant") or "").strip()
    if variant:
        command.extend(["--gguf-variant", variant])
    return command


class LocalServiceManager:
    def __init__(
        self, cleanup: dict, secret_store=None, popen=subprocess.Popen,
        probe=None, port_available=None, executable: str | None = None,
    ) -> None:
        self.cleanup = cleanup
        self.secret_store = secret_store or KeychainSecretStore()
        self._popen = popen
        self._probe = probe or self._probe_server
        self._base_url = validate_loopback_http_url(
            str(cleanup.get("base_url", "http://127.0.0.1:8888/v1"))
        )
        self._process = None
        self._port_available = port_available or self._can_bind_endpoint
        self._executable = executable
        self._owned = False
        self._health = ServiceHealth(ServiceState.STOPPED)
        self._lifecycle_lock = threading.RLock()
        self._stop_requested = threading.Event()

    @property
    def health(self) -> ServiceHealth:
        return self._health

    def connect_or_start(self, timeout_s: float = 120.0) -> ServiceHealth:
        with self._lifecycle_lock:
            return self._connect_or_start_locked(timeout_s)

    def _connect_or_start_locked(self, timeout_s: float) -> ServiceHealth:
        if (
            self._health.state == ServiceState.READY
            and self._owned
            and self._process is not None
            and self._process.poll() is None
        ):
            return self._health

        self._stop_requested.clear()
        self._health = ServiceHealth(ServiceState.STARTING, True, "starting local service")
        if not self._port_available():
            self._health = ServiceHealth(
                ServiceState.ERROR,
                False,
                "refusing to use a pre-existing listener on the cleanup endpoint",
            )
            return self._health
        try:
            command = build_unsloth_command(
                self.cleanup, executable=self._executable
            )
            self._process = self._popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except Exception as exc:
            self._health = ServiceHealth(ServiceState.ERROR, False, str(exc))
            return self._health
        self._owned = True
        lines: queue.Queue[str] = queue.Queue(maxsize=128)
        reader = threading.Thread(
            target=self._read_lines, args=(self._process.stdout, lines),
            daemon=True,
        )
        reader.start()
        deadline = time.monotonic() + timeout_s
        key = ""
        key_persisted = True
        while time.monotonic() < deadline:
            if self._stop_requested.is_set():
                self._stop_owned_locked()
                return self._health
            if self._process.poll() is not None:
                self._health = ServiceHealth(
                    ServiceState.ERROR, True,
                    f"local service exited with {self._process.returncode}",
                )
                return self._health
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                line = ""
            match = _KEY.search(line)
            if match:
                generated_key = match.group(0)
                if generated_key != key:
                    key = generated_key
                    try:
                        self.secret_store.set(CLEANUP_API_KEY_ACCOUNT, key)
                        key_persisted = True
                    except Exception:
                        # The owned child remains usable for this process. Never
                        # include the key or persistence exception in diagnostics.
                        key_persisted = False
            if key and self._probe(key):
                detail = "app-owned local service ready"
                if not key_persisted:
                    detail += "; key persistence unavailable"
                self._health = ServiceHealth(
                    ServiceState.READY, True, detail, key
                )
                return self._health
        self._stop_owned_locked()
        self._health = ServiceHealth(
            ServiceState.ERROR, False, "local service readiness timed out"
        )
        return self._health

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lifecycle_lock:
            self._stop_owned_locked()

    def _stop_owned_locked(self) -> None:
        if not self._owned or self._process is None:
            self._health = ServiceHealth(ServiceState.STOPPED)
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        self._owned = False
        self._process = None
        self._health = ServiceHealth(ServiceState.STOPPED)

    @staticmethod
    def _read_lines(stream, output: queue.Queue[str]) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            try:
                output.put_nowait(line)
            except queue.Full:
                try:
                    output.get_nowait()
                except queue.Empty:
                    pass
                output.put_nowait(line)

    def _probe_server(self, api_key: str) -> bool:
        req = request.Request(
            self._base_url + "/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with open_local_request(req, timeout=1.0) as response:
                body = json.loads(response.read().decode("utf-8"))
            return bool(body.get("data") or body.get("models"))
        except Exception:
            return False

    def _can_bind_endpoint(self) -> bool:
        endpoint = urlsplit(self._base_url)
        family = socket.AF_INET6 if ":" in (endpoint.hostname or "") else socket.AF_INET
        address = (endpoint.hostname or "127.0.0.1", endpoint.port or 80)
        try:
            with socket.socket(family, socket.SOCK_STREAM) as listener:
                listener.bind(address)
            return True
        except OSError:
            return False
