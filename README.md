# whisperflow-local

A 100% local WhisperFlow clone for Windows — global hotkey dictation with a
**local** AI cleanup pass. Tap a hotkey, speak, and clean corrected text (filler
removed, grammar/punctuation fixed) is inserted into whatever text field has
focus. STT and the cleanup LLM both run on-device — **no cloud calls at dictation
time.**

Built as the worked example for a YouTube video whose real deliverable is the
*process*: deep-research → grill → cross-model plan review → Claude Code builds.
See `PLAN.md` (the locked spec), `PLAN-REVIEW-LOG.md` (the Claude↔Codex argument
that hardened it), and `docs/architecture.html` (a visual walkthrough).

## Pipeline

`Ctrl+Win` (toggle) → mic capture (`sounddevice`, 16 kHz mono) → STT
(`faster-whisper large-v3-turbo`, CUDA) → cleanup (local Ollama LLM) → focus-safe
clipboard paste into the active field. A non-activating, click-through PySide6
pill shows live mic level without stealing focus; a tray icon gives a clean quit.

## Requirements

- **Windows 10/11**
- **An NVIDIA GPU** with a recent driver (the STT model runs on CUDA; CPU fallback
  exists but is slow)
- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/) (the package manager)
- **[Ollama](https://ollama.com/download)** for the local cleanup model

## Setup with Claude Code (recommended)

The fastest path — let Claude Code do the install for you:

```bash
git clone https://github.com/cth9191/whisperflow-local.git
cd whisperflow-local
claude            # then ask it to set the project up
```

Then tell Claude Code:

> Set up whisperflow-local on my machine: install the Python deps with uv, make
> sure Ollama is installed and pull the cleanup model from config.yaml, then run
> `python -m whisperflow_local doctor` and fix anything that fails until it passes.

The repo's `CLAUDE.md` tells Claude Code exactly how to do this, including the
common CUDA/cuDNN gotchas on Windows.

## Setup manually

```bash
# 1. Python env + deps
uv venv --python 3.11
uv pip install -e .

# 2. Local cleanup model (Ollama must be installed & running)
ollama pull granite4.1:3b         # or whatever cleanup.model is in config.yaml

# 3. Validate the environment (mic / CUDA / Ollama / clipboard / hotkey)
python -m whisperflow_local doctor
```

If `doctor` reports a CUDA failure, see the cuDNN/cuBLAS note in `CLAUDE.md`.

## Use

```bash
python -m whisperflow_local run                  # live: tap Ctrl+Win to dictate
python -m whisperflow_local selftest             # autonomous end-to-end on a sample
python -m whisperflow_local doctor               # environment health check
python -m whisperflow_local install-autostart    # launch silently on every login
python -m whisperflow_local uninstall-autostart  # remove autostart
```

While recording: **Enter** finishes early, **Esc** cancels (no paste). Quit from
the tray icon.

## Config

All knobs live in `config.yaml` — hotkey, STT model/thresholds, cleanup model +
prompt, insertion mode, max recording length, sounds, logging. Logging is
**metadata-only by default**; transcript text is logged only if you opt in.

## macOS / Linux

**This is a Windows v1 — it won't run as-is on a Mac.** The core (audio capture,
the local Ollama cleanup, the state machine, the Qt pill) is cross-platform, but
several pieces are Windows-specific and need a Mac equivalent:

- **STT engine** — there's no CUDA on Mac. Swap `faster-whisper`/CUDA for
  **`mlx-whisper`** or **`whisper.cpp`** (Apple-Silicon/Metal). *(biggest change)*
- **Overlay** (`overlay.py`) — the non-activating, click-through window uses Win32
  styles; on macOS that's a Cocoa `NSPanel` (non-activating + `ignoresMouseEvents`).
- **Focus-safe insert** (`inserter.py`) — uses Win32 focus APIs + `Ctrl+V`; macOS
  needs the **Accessibility API** for focus and **`Cmd+V`** to paste.
- **Hotkey** — there's no `Win` key; pick something like `Cmd+Opt`, and macOS will
  require granting **Accessibility permission**.
- **Autostart** (`autostart.py`) — a Startup `.lnk` becomes a **LaunchAgent**
  plist in `~/Library/LaunchAgents`.

Two good paths: **(a)** point Claude Code at this repo and ask it to *port to
macOS* — the clean way is a small platform layer (`_win`/`_mac` implementations
of inserter/overlay/hotkey/autostart/stt) so `app.py` never changes; or **(b)**
re-run the build pipeline targeting macOS from scratch. Note that Mac already has
strong **local** dictation tools (superwhisper, MacWhisper), so the "WhisperFlow
is cloud-only" motivation is Windows-specific.

## Status

v1, Windows-only. **In:** toggle dictation, local cleanup, focus-safe paste,
overlay pill, tray + quit, autostart, Esc-cancel, failure cues. **Out of scope
(v2):** per-app tone, hold-to-talk, streaming STT, cross-platform, a packaged
installer. See `PLAN.md`.
