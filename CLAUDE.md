# whisperflow-local — guide for Claude Code

This repo is now targeted at macOS Apple Silicon: tap `Cmd+Shift+Space`, speak,
and cleaned text is pasted into the focused field. STT runs locally with
`lightning-whisper-mlx`; cleanup uses an authenticated local Unsloth service
started and owned by the app. No cloud calls occur at dictation time after
one-time model downloads.

## Setup

1. Use Python 3.11+ with `uv`:

   ```bash
   uv venv --python 3.11
   uv pip install -e .
   ```

2. Run doctor from the venv:

   ```bash
   .venv/bin/python -m whisperflow_local doctor
   ```

   It checks microphone input, macOS permissions, the MLX STT backend, local
   cleanup configuration and model presence, clipboard access, and hotkey/overlay
   imports. It does not authenticate to or probe an existing cleanup listener.

3. Run the app:

   ```bash
   .venv/bin/python -m whisperflow_local run
   ```

## macOS Permissions

Grant Accessibility permission to the terminal/app that runs whisperflow-local so
it can validate focus, synthesize paste, and observe global Escape cancellation.
The dictation hotkey itself uses native Carbon registration. Grant Microphone
permission for capture. If dictation or paste does nothing, check System Settings
-> Privacy & Security -> Accessibility.

## Model Choices

- STT model and batch size are selected by the active performance profile.
- Cleanup default: Unsloth Studio serving `unsloth/Qwen3.5-4B-MTP-GGUF` as
  `default` on a loopback endpoint. `run` owns the service lifecycle and passes
  its generated credential directly to the cleanup client. If cleanup is not
  ready, dictated text is retained for recovery rather than sent elsewhere.

## Commands

```bash
.venv/bin/python -m whisperflow_local run
.venv/bin/python -m whisperflow_local selftest
.venv/bin/python -m whisperflow_local doctor
.venv/bin/python -m whisperflow_local delete-cleanup-key
.venv/bin/python -m whisperflow_local install-autostart
.venv/bin/python -m whisperflow_local uninstall-autostart
```

## Files

`whisperflow_local/app.py` is the orchestrator and state machine.
`audio.py` records 16 kHz mono float32 audio.
`stt.py` uses `lightning-whisper-mlx` for local Apple Silicon transcription.
`cleanup.py` supports loopback Ollama and app-managed OpenAI-compatible servers;
config currently selects the managed Unsloth service path.
`inserter.py` snapshots the focused Accessibility element and window, uses a
multi-format NSPasteboard transaction, and pastes with `Cmd+V` only after revalidation.
`autostart.py` writes a user LaunchAgent on macOS.
