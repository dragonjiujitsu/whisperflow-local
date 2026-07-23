# whisperflow-local — guide for Claude Code

This repo is now targeted at macOS Apple Silicon: tap `Cmd+Shift+Space`, speak,
and cleaned text is pasted into the focused field. STT runs locally with
`lightning-whisper-mlx`; cleanup prefers local Unsloth Studio server inference
with direct Unsloth CLI fallback. No cloud calls at dictation time after one-time
model downloads.

## Setup

1. Use Python 3.11+ with `uv`:

   ```bash
   uv venv --python 3.11
   uv pip install -e .
   ```

2. Optionally inspect the persistent cleanup-server command:

   ```bash
   .venv/bin/python -m whisperflow_local cleanup-server-command
   ```

   Normal `run` owns this lifecycle, stores the generated key in macOS Keychain,
   and falls back to direct `unsloth-cli` inference if the warm service is unavailable.

3. Run doctor from the venv:

   ```bash
   .venv/bin/python -m whisperflow_local doctor
   ```

   It checks microphone input, the MLX STT backend, the selected cleanup provider
   plus model, clipboard access, and hotkey/overlay imports.

4. Run the app:

   ```bash
   .venv/bin/python -m whisperflow_local run
   ```

## macOS Permissions

Grant Accessibility permission to the terminal/app that runs whisperflow-local so
`pynput` can observe the global hotkey and synthesize paste. Grant Microphone
permission for capture. If the hotkey or paste does nothing, check System Settings
-> Privacy & Security -> Accessibility.

## Model Choices

- STT default: `distil-large-v3` via `lightning-whisper-mlx`, `quant: null`.
  This is the speed-first local dictation default for Apple Silicon.
- Cleanup default: Unsloth Studio serving `unsloth/Qwen3.5-4B-MTP-GGUF` as
  `default` on `http://localhost:8888/v1`, with direct Unsloth CLI fallback to
  `Qwen3.5-4B-UD-Q4_K_XL.gguf`. The 4B model is a better latency fit than the
  local 35B Qwen cache.

If quality is not good enough, switch `stt.model` to `large-v3` and reduce `stt.batch_size` to `6` if latency remains acceptable.

## Commands

```bash
.venv/bin/python -m whisperflow_local run
.venv/bin/python -m whisperflow_local selftest
.venv/bin/python -m whisperflow_local doctor
.venv/bin/python -m whisperflow_local cleanup-server-command
.venv/bin/python -m whisperflow_local set-cleanup-key
.venv/bin/python -m whisperflow_local delete-cleanup-key
.venv/bin/python -m whisperflow_local install-autostart
.venv/bin/python -m whisperflow_local uninstall-autostart
```

## Files

`whisperflow_local/app.py` is the orchestrator and state machine.
`audio.py` records 16 kHz mono float32 audio.
`stt.py` uses `lightning-whisper-mlx` for local Apple Silicon transcription.
`cleanup.py` supports Unsloth CLI, Ollama, and OpenAI-compatible servers; config
currently selects the OpenAI-compatible Unsloth Studio path with Unsloth CLI fallback.
`inserter.py` snapshots the focused Accessibility element and window, uses a
multi-format NSPasteboard transaction, and pastes with `Cmd+V` only after revalidation.
`autostart.py` writes a user LaunchAgent on macOS.
