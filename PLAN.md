# Plan: 100% Local WhisperFlow-Style Dictation for macOS

## Goal

A macOS Apple Silicon dictation app whose runtime is fully local: tap
`Cmd+Shift+Space`, speak, stop, and cleaned text is inserted into the frontmost
field. Speech-to-text runs locally through MLX/Metal. Cleanup prefers a local
Unsloth Studio server, with direct Unsloth CLI inference as fallback.

## Current Architecture

1. **Capture** - `sounddevice` records 16 kHz mono float32 audio into a bounded
   buffer and sends RMS levels to the overlay.
2. **Hotkey/state machine** - `pynput` listens for `Cmd+Shift+Space`; Qt signals
   marshal hotkey and worker events back to the UI thread.
3. **STT** - `lightning-whisper-mlx` with `distil-large-v3`, `quant: null`,
   selected for Apple Silicon speed while keeping strong English dictation
   quality. Set `quant: null` or switch to `large-v3` if accuracy needs to win
   over latency.
4. **Cleanup** - Unsloth Studio serving `unsloth/Qwen3.5-4B-MTP-GGUF` as
   `default` through an OpenAI-compatible localhost API; if the server/key is
   unavailable, direct Unsloth CLI runs the cached `Qwen3.5-4B-UD-Q4_K_XL.gguf`.
5. **Insertion** - snapshot the frontmost macOS process at stop time, then
   re-check it before inserting. Paste uses `pbcopy`/`pbpaste` plus synthetic
   `Cmd+V`; type mode remains available by config.
6. **Overlay** - PySide6 always-on-top pill that does not accept focus and is
   transparent to mouse events.
7. **Autostart** - per-user LaunchAgent under `~/Library/LaunchAgents`.
8. **Doctor** - validates microphone input, MLX package presence, cleanup provider/model,
   clipboard, and hotkey/overlay imports.

## Model Decision

Default STT model: `distil-large-v3` through `lightning-whisper-mlx`, unquantized. This is the best default for local Mac dictation because it avoids
cloud calls, uses Apple Silicon acceleration, and is faster than full `large-v3`
for short utterances.

Default cleanup model: the cached Unsloth `unsloth/Qwen3.5-4B-MTP-GGUF`, served
persistently by Unsloth Studio when available and loaded directly from
`Qwen3.5-4B-UD-Q4_K_XL.gguf` as fallback. The local 4B Qwen GGUF is the practical
cleanup default; the 35B cache is reserved for quality experiments where latency
is acceptable.

## Done Criteria

- `uv pip install -e .` succeeds on macOS Apple Silicon.
- `python -m whisperflow_local doctor` passes in a logged-in GUI session with
  microphone permission, Accessibility permission, and the selected cleanup
  provider available.
- `python -m whisperflow_local selftest` transcribes, cleans, and inserts into
  the Qt target field.
- `python -m whisperflow_local run` starts the tray app and responds to the
  configured hotkey.
