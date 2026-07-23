"""Lifecycle for the warm localhost cleanup service."""
from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from urllib import request

from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore

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


def build_unsloth_command(cleanup: dict) -> list[str]:
    base_url = str(cleanup.get("base_url", "http://127.0.0.1:8888/v1"))
    authority = base_url.split("//", 1)[-1].split("/", 1)[0]
    host, _, port = authority.partition(":")
    command = [
        "unsloth", "run", "--model",
        str(cleanup.get("server_model") or cleanup.get("model_path")),
        "--host", host or "127.0.0.1",
        "--port", port or "8888",
        "--disable-tools",
    ]
    variant = str(cleanup.get("server_gguf_variant") or "").strip()
    if variant:
        command.extend(["--gguf-variant", variant])
    return command


class LocalServiceManager:
    def __init__(
        self, cleanup: dict, secret_store=None, popen=subprocess.Popen,
        probe=None,
    ) -> None:
        self.cleanup = cleanup
        self.secret_store = secret_store or KeychainSecretStore()
        self._popen = popen
        self._probe = probe or self._probe_server
        self._process = None
        self._owned = False
        self._health = ServiceHealth(ServiceState.STOPPED)

    @property
    def health(self) -> ServiceHealth:
        return self._health

    def connect_or_start(self, timeout_s: float = 120.0) -> ServiceHealth:
        stored_key = self.secret_store.get(CLEANUP_API_KEY_ACCOUNT)
        if stored_key and self._probe(stored_key):
            self._health = ServiceHealth(
                ServiceState.READY, False, "connected to existing local service",
                stored_key,
            )
            return self._health
        self._health = ServiceHealth(ServiceState.STARTING, True, "starting local service")
        command = build_unsloth_command(self.cleanup)
        try:
            self._process = self._popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except Exception as exc:
            self._health = ServiceHealth(ServiceState.ERROR, False, str(exc))
            return self._health
        self._owned = True
        lines: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(
            target=self._read_lines, args=(self._process.stdout, lines),
            daemon=True,
        )
        reader.start()
        deadline = time.monotonic() + timeout_s
        key = stored_key
        while time.monotonic() < deadline:
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
                key = match.group(0)
                self.secret_store.set(CLEANUP_API_KEY_ACCOUNT, key)
            if key and self._probe(key):
                self._health = ServiceHealth(
                    ServiceState.READY, True, "app-owned local service ready", key
                )
                return self._health
        self.stop()
        self._health = ServiceHealth(
            ServiceState.ERROR, False, "local service readiness timed out"
        )
        return self._health

    def stop(self) -> None:
        if not self._owned or self._process is None:
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
            output.put(line)

    def _probe_server(self, api_key: str) -> bool:
        base_url = str(self.cleanup.get("base_url", "http://127.0.0.1:8888/v1"))
        req = request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with request.urlopen(req, timeout=1.0) as response:
                body = json.loads(response.read().decode("utf-8"))
            return bool(body.get("data") or body.get("models"))
        except Exception:
            return False
