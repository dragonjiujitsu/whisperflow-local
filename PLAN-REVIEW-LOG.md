# Plan Review Log

This file now tracks the macOS port, not the original prototype direction.

## Resolved Changes

- Replaced non-macOS STT with `lightning-whisper-mlx` on Apple Silicon.
- Removed non-macOS runtime dependencies and platform branches from the active
  package.
- Switched insertion to macOS frontmost-process checks and `Cmd+V`.
- Switched launch-on-login to a user LaunchAgent.
- Updated the hotkey to `Cmd+Shift+Space` using valid `pynput` syntax.
- Updated PySide6 to `6.10.3` after the older pin crashed on this Mac.
- Selected `distil-large-v3` for STT and the local Unsloth
  `unsloth/Qwen3.5-4B-MTP-GGUF` cleanup model.

## Verification

- `doctor` passes with the Unsloth Studio server and API key.
- `doctor` also passes without the API key by confirming the direct Unsloth CLI
  fallback is available.
- `selftest` passes end to end: MLX STT, Unsloth cleanup, focus-checked paste
  into TextEdit, and inserted-text verification.
- The live tray app starts without immediate startup errors.
