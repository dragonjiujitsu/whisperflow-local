"""Local LLM cleanup pass via Ollama.

Transcript-only editing with an anti-injection guard: if the model's output
expands suspiciously beyond the input (a sign it answered/obeyed the transcript
instead of cleaning it), we reject and fall back to the raw transcript.
"""
from __future__ import annotations

import ollama


class Cleaner:
    def __init__(self, cfg: dict, timeout_s: float = 120.0) -> None:
        self._model = cfg["model"]
        self._system = cfg["prompt"]
        # Qwen3 honors the "/no_think" soft switch to skip reasoning — keeps
        # cleanup fast and prevents verbose <think> output tripping the guard.
        if "qwen" in self._model.lower():
            self._system = self._system.rstrip() + "\n/no_think"
        self._keep_alive = cfg.get("keep_alive", "30m")
        self._options = dict(cfg.get("options") or {})
        self._max_ratio = float(cfg.get("max_expansion_ratio", 2.5))
        self._client = ollama.Client(timeout=timeout_s)

    def warmup(self) -> None:
        """Load the model into VRAM so the first real dictation isn't cold."""
        self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": "ok"}],
            keep_alive=self._keep_alive,
            options={"num_predict": 1},
        )

    def clean(self, transcript: str) -> str:
        transcript = transcript.strip()
        if not transcript:
            return ""

        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system},
                {"role": "user", "content": transcript},
            ],
            keep_alive=self._keep_alive,
            options=self._options,
        )
        # disable thinking when the client/model supports it; ignore otherwise
        try:
            resp = self._client.chat(think=False, **kwargs)
        except TypeError:
            resp = self._client.chat(**kwargs)

        out = (resp["message"]["content"] or "").strip()
        if not out:
            return transcript

        # collapse newlines/whitespace to a single line — a stray newline pasted
        # into a chat box submits early and splits the message into two.
        out = " ".join(out.split())

        # anti-injection / runaway guard
        if len(out) > len(transcript) * self._max_ratio:
            return transcript
        return out
