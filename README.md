# whisperflow-local

A 100% local WhisperFlow clone for Windows — global hotkey dictation with a
**local** AI cleanup pass. Toggle a hotkey, speak, and clean corrected text
(filler removed, grammar/punctuation fixed) is inserted into whatever text field
has focus. STT and the cleanup LLM run on-device — no cloud calls at dictation
time.

Built as the worked example for a YouTube video whose real deliverable is the
*process*: deep-research → grill → cross-model plan review → Claude Code builds.
See `PLAN.md` (the locked spec) and `PLAN-REVIEW-LOG.md` (the Claude↔Codex
argument that hardened it).

## Pipeline

`Ctrl+Win` (toggle) → mic capture (`sounddevice`) → STT
(`faster-whisper large-v3-turbo`, CUDA) → cleanup (Ollama, local) → focus-safe
clipboard paste into the active field. A non-activating, click-through PySide6
pill shows live mic level without stealing focus.

## Setup

```bash
uv venv --python 3.11
uv pip install -e .
ollama pull qwen3.5:4b            # or set cleanup.model in config.yaml
python -m whisperflow_local doctor    # validate mic / CUDA / Ollama / clipboard
```

## Use

```bash
python -m whisperflow_local run        # live: toggle with Ctrl+Win
python -m whisperflow_local selftest   # autonomous end-to-end on a spoken sample
python -m whisperflow_local doctor     # environment health check
```

## Config

All knobs live in `config.yaml` (hotkey, STT model/thresholds, cleanup model +
prompt, insertion mode, logging). Logging is metadata-only by default; transcript
text is logged only if you opt in.

## Status

v1, Windows-only. Out of scope: per-app tone, tray icon, hold-to-talk, streaming
STT, cross-platform, installer. See `PLAN.md`.
