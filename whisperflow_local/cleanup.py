"""Local transcript cleanup through Ollama or an OpenAI-compatible server.

Transcript-only editing with an anti-injection guard: if the model output expands
suspiciously beyond the input, we reject it and fall back to the raw transcript.
"""
from __future__ import annotations

import json
import os
from threading import Event
from urllib.error import URLError
from urllib import request
from urllib.parse import urlsplit

import ollama

from .local_endpoint import open_local_request, validate_loopback_http_url


class CleanupCancelled(RuntimeError):
    pass


def validate_ollama_host(value: str) -> str:
    """Normalize OLLAMA_HOST after enforcing a loopback-only HTTP endpoint."""
    raw = str(value).strip()
    if not raw:
        raw = "127.0.0.1:11434"
    if "://" not in raw:
        raw = f"http://{raw}"

    parts = urlsplit(raw)
    if parts.path not in {"", "/"}:
        raise ValueError("OLLAMA_HOST must not include a path")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("OLLAMA_HOST must include a valid port") from exc
    if port is None:
        host = parts.hostname or ""
        authority_host = f"[{host}]" if ":" in host else host
        raw = f"http://{authority_host}:11434"

    try:
        return validate_loopback_http_url(raw)
    except ValueError as exc:
        raise ValueError(
            "OLLAMA_HOST must be an HTTP loopback endpoint"
        ) from exc


class Cleaner:
    def __init__(self, cfg: dict, timeout_s: float = 120.0) -> None:
        self._provider = str(cfg.get("provider", "ollama")).lower()
        if self._provider not in {"ollama", "openai-compatible", "omlx"}:
            raise ValueError(f"unsupported cleanup provider: {self._provider}")
        self._model = cfg["model"]
        self._system = cfg["prompt"]
        # Qwen-family models honor the "/no_think" soft switch in common serving
        # stacks. It keeps cleanup fast and avoids verbose reasoning output.
        if "qwen" in self._model.lower():
            self._system = self._system.rstrip() + "\n/no_think"
        self._keep_alive = cfg.get("keep_alive", "30m")
        self._options = dict(cfg.get("options") or {})
        self._max_ratio = float(cfg.get("max_expansion_ratio", 2.5))
        self._timeout_s = timeout_s
        self._openai_base_url = validate_loopback_http_url(
            str(cfg.get("base_url", "http://localhost:8888/v1"))
        )
        # Managed cleanup credentials are capability tokens for the child this
        # process just started. They must only arrive through set_api_key after
        # LocalServiceManager proves that child READY and owned.
        self._openai_api_key = ""
        self._client = None
        if self._provider == "ollama":
            host = validate_ollama_host(os.environ.get("OLLAMA_HOST", ""))
            self._client = ollama.Client(host=host, timeout=timeout_s)

    def set_api_key(self, api_key: str) -> None:
        """Refresh the local service credential after app-owned startup."""
        self._openai_api_key = api_key.strip()

    def warmup(self) -> None:
        """Load the model so the first real dictation is not cold."""
        if self._provider == "ollama":
            self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": "ok"}],
                keep_alive=self._keep_alive,
                options={"num_predict": 1},
            )
            return
        if self._provider in {"openai-compatible", "omlx"}:
            self._chat_openai_compatible("ok", max_tokens=1)
            return
        raise ValueError(f"unsupported cleanup provider: {self._provider}")

    def clean(
        self, transcript: str, cancelled: Event | None = None,
        instruction: str = "",
    ) -> str:
        transcript = transcript.strip()
        if not transcript:
            return ""
        self._check_cancelled(cancelled)

        system = self._system
        if instruction.strip():
            system += "\n\nWriting mode for this request: " + instruction.strip()

        if self._provider == "ollama":
            out = self._clean_ollama(transcript, cancelled=cancelled, system=system)
        elif self._provider in {"openai-compatible", "omlx"}:
            out = self._chat_openai_compatible(
                transcript, cancelled=cancelled, system=system
            )
        else:
            raise ValueError(f"unsupported cleanup provider: {self._provider}")

        out = out.strip()
        if not out:
            return transcript

        # Collapse whitespace to a single line. A stray newline pasted into a
        # chat box can submit early and split the message.
        out = " ".join(out.split())

        # Anti-injection / runaway guard.
        if len(out) > len(transcript) * self._max_ratio:
            return transcript
        return out

    def _clean_ollama(
        self, transcript: str, cancelled: Event | None = None,
        system: str | None = None,
    ) -> str:
        self._check_cancelled(cancelled)
        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system or self._system},
                {"role": "user", "content": transcript},
            ],
            keep_alive=self._keep_alive,
            options=self._options,
        )
        # Disable thinking when the client/model supports it; ignore otherwise.
        try:
            resp = self._client.chat(think=False, **kwargs)
        except TypeError:
            resp = self._client.chat(**kwargs)
        self._check_cancelled(cancelled)
        return resp["message"]["content"] or ""

    def _chat_openai_compatible(
        self, transcript: str, max_tokens: int | None = None,
        cancelled: Event | None = None, system: str | None = None,
    ) -> str:
        self._check_cancelled(cancelled)
        if not self._openai_api_key:
            raise RuntimeError(
                "cleanup service credential unavailable; managed service is not READY"
            )

        options = self._openai_options(max_tokens=max_tokens)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system or self._system},
                {"role": "user", "content": transcript},
            ],
            "stream": False,
            **options,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self._openai_base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self._openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with open_local_request(req, timeout=self._timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"cleanup server unavailable at {self._openai_base_url}") from exc
        self._check_cancelled(cancelled)
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return message.get("content") or ""

    def _openai_options(self, max_tokens: int | None = None) -> dict:
        options: dict = {}
        if "temperature" in self._options:
            options["temperature"] = self._options["temperature"]
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        elif "max_tokens" in self._options:
            options["max_tokens"] = self._options["max_tokens"]
        elif "num_predict" in self._options:
            options["max_tokens"] = self._options["num_predict"]
        return options

    @staticmethod
    def _check_cancelled(cancelled: Event | None) -> None:
        if cancelled is not None and cancelled.is_set():
            raise CleanupCancelled("cleanup cancelled")
