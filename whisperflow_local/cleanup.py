"""Local transcript cleanup through Unsloth, Ollama, or an OpenAI-compatible server.

Transcript-only editing with an anti-injection guard: if the model output expands
suspiciously beyond the input, we reject it and fall back to the raw transcript.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from threading import Event
from urllib.error import URLError
from urllib import request

import ollama


class CleanupCancelled(RuntimeError):
    pass


class Cleaner:
    def __init__(self, cfg: dict, timeout_s: float = 120.0) -> None:
        self._provider = str(cfg.get("provider", "ollama")).lower()
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
        self._openai_base_url = str(cfg.get("base_url", "http://localhost:8888/v1")).rstrip("/")
        self._openai_api_key = self._resolve_api_key(cfg)
        self._model_path = str(cfg.get("model_path") or self._model)
        self._fallback_provider = str(cfg.get("fallback_provider", "")).lower()
        self._client = ollama.Client(timeout=timeout_s) if self._provider == "ollama" else None

    def set_api_key(self, api_key: str) -> None:
        """Refresh the local service credential after app-owned startup."""
        self._openai_api_key = api_key.strip()

    def warmup(self) -> None:
        """Load the model so the first real dictation is not cold."""
        if self._provider == "unsloth-cli":
            self._chat_unsloth_cli("ok", max_tokens=1)
            return
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

        if self._provider == "unsloth-cli":
            out = self._chat_unsloth_cli(transcript, cancelled=cancelled, system=system)
        elif self._provider == "ollama":
            out = self._clean_ollama(transcript, cancelled=cancelled, system=system)
        elif self._provider in {"openai-compatible", "omlx"}:
            try:
                out = self._chat_openai_compatible(transcript, cancelled=cancelled, system=system)
            except CleanupCancelled:
                raise
            except Exception:
                if self._fallback_provider != "unsloth-cli":
                    raise
                out = self._chat_unsloth_cli(transcript, cancelled=cancelled, system=system)
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

    def _chat_unsloth_cli(
        self, transcript: str, max_tokens: int | None = None,
        cancelled: Event | None = None, system: str | None = None,
    ) -> str:
        self._check_cancelled(cancelled)
        if shutil.which("unsloth") is None:
            raise RuntimeError("unsloth CLI not found on PATH")

        max_new_tokens = max_tokens
        if max_new_tokens is None:
            max_new_tokens = int(self._options.get("max_tokens") or self._options.get("num_predict") or 2048)

        cmd = [
            "unsloth",
            "inference",
            self._model_path,
            transcript,
            "--system-prompt",
            system or self._system,
            "--max-new-tokens",
            str(max_new_tokens),
            "--temperature",
            str(self._options.get("temperature", 0.2)),
            "--no-think",
            "--no-server",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + self._timeout_s
        try:
            while True:
                self._check_cancelled(cancelled)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, self._timeout_s)
                try:
                    stdout, stderr = proc.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except (CleanupCancelled, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, output=stdout, stderr=stderr
            )
        return self._parse_unsloth_output(stdout)

    def _parse_unsloth_output(self, output: str) -> str:
        marker = "Assistant:"
        if marker in output:
            return output.rsplit(marker, 1)[1].strip()
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _chat_openai_compatible(
        self, transcript: str, max_tokens: int | None = None,
        cancelled: Event | None = None, system: str | None = None,
    ) -> str:
        self._check_cancelled(cancelled)
        if not self._openai_api_key:
            raise RuntimeError("cleanup API key missing; set cleanup.api_key or its api_key_env")

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
            with request.urlopen(req, timeout=self._timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"cleanup server unavailable at {self._openai_base_url}") from exc
        self._check_cancelled(cancelled)
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return message.get("content") or ""

    def _resolve_api_key(self, cfg: dict) -> str:
        env_name = str(cfg.get("api_key_env", "")).strip()
        if env_name:
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
        configured = str(cfg.get("api_key", "")).strip()
        if configured:
            return configured
        try:
            from .keychain import CLEANUP_API_KEY_ACCOUNT, KeychainSecretStore

            account = str(
                cfg.get("api_key_keychain_account") or CLEANUP_API_KEY_ACCOUNT
            )
            return KeychainSecretStore().get(account).strip()
        except Exception:
            return ""

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
