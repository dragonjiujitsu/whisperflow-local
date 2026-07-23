# whisperflow-local macOS Port Handoff

Date: 2026-07-10  
Repo: `/Users/shawnvanbrunt/Developer/whisperflow-local`  
Status: macOS Apple Silicon port implemented and verified

## Goal

The original goal was to take the existing `whisperflow-local` repo and make it
work for macOS instead of Windows. The second requirement was to determine which
local model stack should be used for the app.

The intended product is a fully local WhisperFlow-style dictation app:

1. Press a global hotkey.
2. Speak.
3. Stop recording.
4. Transcribe locally.
5. Clean up the transcript locally with an LLM.
6. Paste the cleaned text into the currently focused text field.

No cloud inference should be required at dictation time. The only network use is
one-time model/tool setup.

## High-Level Result

The repo is now targeted at macOS Apple Silicon.

The active runtime is:

- Hotkey: `Cmd+Shift+Space`
- Audio capture: `sounddevice`, 16 kHz mono float32
- Speech-to-text: `lightning-whisper-mlx` on Apple Silicon/Metal
- STT model: `distil-large-v3`, unquantized
- Cleanup preferred runtime: Unsloth Studio OpenAI-compatible local server
- Cleanup fallback runtime: direct `unsloth` CLI inference
- Cleanup model: cached Unsloth `unsloth/Qwen3.5-4B-MTP-GGUF`
- Cleanup GGUF fallback file: `Qwen3.5-4B-UD-Q4_K_XL.gguf`
- Insertion: macOS pasteboard via `pbcopy`/`pbpaste`, then synthetic `Cmd+V`
- Focus safety: frontmost macOS process is captured before insertion and checked again before paste
- Autostart: user LaunchAgent under `~/Library/LaunchAgents`

The Windows/CUDA path was removed from the active package. The codebase no
longer depends on Win32 APIs, SAPI, CUDA, `faster-whisper`, `pywin32`, Windows
startup shortcuts, `.ico` icon generation, or Windows overlay flags.

## Model Decision

### STT Model

Chosen default:

```yaml
stt:
  model: "distil-large-v3"
  quant: null
  batch_size: 12
```

Runtime:

```text
lightning-whisper-mlx + MLX/Metal
```

Why this model:

- It runs locally on Apple Silicon through MLX.
- It is much faster than full `large-v3` for short dictation.
- It keeps strong English dictation quality.
- It worked in the project Python 3.11 venv with `mlx==0.29.3` and
  `mlx-metal==0.29.3`.

Important detail:

Newer MLX was available elsewhere on the machine, but the project venv is pinned
to the older MLX version because the quantized path had compatibility problems
during testing. The current default is intentionally unquantized:

```yaml
quant: null
```

If quality needs to win over latency later, the likely next STT experiment is:

```yaml
stt:
  model: "large-v3"
  batch_size: 6
```

### Cleanup Model

Preferred runtime:

```text
Unsloth Studio OpenAI-compatible server
```

Preferred model:

```text
unsloth/Qwen3.5-4B-MTP-GGUF
```

Server-facing model name:

```yaml
model: "default"
```

Fallback runtime:

```text
direct unsloth CLI inference
```

Fallback local GGUF:

```text
/Users/shawnvanbrunt/.cache/huggingface/hub/models--unsloth--Qwen3.5-4B-MTP-GGUF/snapshots/86835bf9949e4d14d6860f7910b1340ad4f271a9/Qwen3.5-4B-UD-Q4_K_XL.gguf
```

Why this model:

- It is already cached locally on this Mac.
- The 4B size is realistic for post-dictation cleanup latency.
- It produces clean transcript edits without requiring cloud inference.
- It is much more practical for this app than the local 35B Qwen cache.

Not chosen as default:

```text
unsloth/Qwen3.6-35B-A3B-GGUF
```

Reason: the 35B cache exists locally, but it is too heavy for fast cleanup after
short dictation. It should be reserved for quality experiments, not default UX.

## Local AI Frameworks on This Machine

Relevant local installs:

- Unsloth Studio venv:
  `/Users/shawnvanbrunt/.unsloth/studio/unsloth_studio/`
- Unsloth CLI launcher:
  `/Users/shawnvanbrunt/.local/bin/unsloth`
- Project venv:
  `/Users/shawnvanbrunt/Developer/whisperflow-local/.venv/`
- Homebrew MLX:
  `/opt/homebrew/lib/python3.14/site-packages/`

Important architecture decision:

The app does not import the Unsloth Studio Python 3.13 packages into the project
Python 3.11 venv. That would make the environment fragile. Instead:

- STT runs in the project venv.
- Cleanup uses either:
  - HTTP to Unsloth Studio's local OpenAI-compatible server, or
  - the `unsloth` launcher as a subprocess fallback.

This keeps interpreter boundaries clean.

## Major Code Changes

### `pyproject.toml`

Changed dependencies from the Windows/CUDA stack to the macOS/MLX stack.

Removed:

- `pywin32`
- `faster-whisper`
- `pyperclip`

Added or retained:

- `PySide6==6.10.3`
- `sounddevice==0.5.1`
- `numpy==2.2.1`
- `lightning-whisper-mlx==0.0.10`
- `mlx==0.29.3`
- `mlx-metal==0.29.3`
- `pynput==1.7.7`
- `ollama==0.4.5`
- `PyYAML==6.0.2`

Note: `ollama` remains available as a supported cleanup provider, but it is not
the default runtime now.

### `config.yaml`

The config now reflects macOS and the Unsloth server/fallback design.

Key sections:

```yaml
hotkey:
  combo: "<cmd>+<shift>+<space>"

stt:
  model: "distil-large-v3"
  quant: null
  batch_size: 12

cleanup:
  provider: "openai-compatible"
  fallback_provider: "unsloth-cli"
  base_url: "http://localhost:8888/v1"
  api_key_env: "UNSLOTH_API_KEY"
  api_key: ""
  model: "default"
  model_path: "/Users/shawnvanbrunt/.cache/huggingface/hub/models--unsloth--Qwen3.5-4B-MTP-GGUF/snapshots/86835bf9949e4d14d6860f7910b1340ad4f271a9/Qwen3.5-4B-UD-Q4_K_XL.gguf"
  server_model: "unsloth/Qwen3.5-4B-MTP-GGUF"
  server_gguf_variant: "UD-Q4_K_XL"
```

The API key is intentionally not committed. It is read from:

```bash
UNSLOTH_API_KEY
```

### `whisperflow_local/stt.py`

Replaced Windows/CUDA STT with macOS MLX STT.

Important implementation detail:

The code still instantiates `LightningWhisperMLX` to download/load the model,
but transcription uses the lower-level
`lightning_whisper_mlx.transcribe.transcribe_audio` function directly with a
NumPy audio array.

Why:

- This avoids needing `ffmpeg`.
- It transcribes the in-memory recorder audio directly.
- It keeps the pipeline local and simple.

The STT module now:

- Rejects non-macOS platforms.
- Rejects too-short audio.
- Rejects very low RMS audio.
- Requires 16 kHz input.
- Uses `condition_on_previous_text=False`.

### `whisperflow_local/cleanup.py`

This became provider-aware.

Supported providers:

- `openai-compatible`
- `omlx` as a backward-compatible alias for the same HTTP path
- `unsloth-cli`
- `ollama`

Default behavior:

1. Try OpenAI-compatible HTTP cleanup through Unsloth Studio:
   `http://localhost:8888/v1/chat/completions`
2. Read the API key from `UNSLOTH_API_KEY`.
3. Use `model: "default"`.
4. If the server or API key is unavailable, fallback to direct `unsloth-cli`.

The cleanup layer also keeps the anti-injection/runaway guard:

- It collapses output whitespace to one line.
- It rejects suspiciously expanded output using `max_expansion_ratio`.
- It does not follow instructions embedded inside the dictated transcript.

### `whisperflow_local/__main__.py`

Updated CLI and verification.

Commands now include:

```bash
python -m whisperflow_local doctor
python -m whisperflow_local selftest
python -m whisperflow_local run
python -m whisperflow_local cleanup-server-command
python -m whisperflow_local install-autostart
python -m whisperflow_local uninstall-autostart
```

New helper:

```bash
python -m whisperflow_local cleanup-server-command
```

It prints the exact Unsloth Studio server command based on `config.yaml`, plus
the reminder to export `UNSLOTH_API_KEY`.

`doctor` now checks:

- Microphone devices.
- MLX STT package presence.
- Cleanup provider health.
- Direct Unsloth CLI fallback availability.
- Clipboard access.
- Hotkey/overlay imports.
- Autostart status as informational.

`selftest` now uses TextEdit as a real macOS insertion target. This was an
important fix. Early selftests tried to paste into a Qt test window, but macOS
would not always foreground the unbundled Python/Qt process from the terminal.
TextEdit gives a real, user-facing macOS text field and better represents live
usage.

Selftest now verifies:

1. Sample audio exists or is generated.
2. MLX STT returns non-empty text.
3. Unsloth cleanup returns non-empty text.
4. Filler/disfluency is reduced.
5. Focus-checked paste lands in TextEdit.

### `whisperflow_local/clipboard.py`

New macOS clipboard helper.

Uses:

- `pbpaste`
- `pbcopy`

This replaces the Windows clipboard path and removes the need for `pyperclip`.

### `whisperflow_local/inserter.py`

Rewritten for macOS.

Current behavior:

- Captures the frontmost macOS process PID using `System Events`.
- Before insertion, verifies the same process is still frontmost.
- If focus changed, insertion aborts.
- Paste uses the macOS pasteboard and synthetic `Cmd+V`.
- Type mode remains available in config.

This avoids leaking dictated text into the wrong app when the user changes focus
while STT/cleanup is running.

### `whisperflow_local/autostart.py`

Replaced Windows startup shortcut behavior with a macOS LaunchAgent.

LaunchAgent location:

```text
~/Library/LaunchAgents
```

Commands:

```bash
python -m whisperflow_local install-autostart
python -m whisperflow_local uninstall-autostart
```

### `whisperflow_local/overlay.py`

Removed Win32 overlay flags.

The PySide6 overlay now uses Qt/macOS-friendly behavior:

- Always on top.
- Does not accept focus.
- Shows without activating.
- Transparent for mouse events.

The goal is to preserve a non-intrusive recording pill without stealing focus
from the target app.

### `whisperflow_local/app.py`

The orchestrator was kept, but Windows-specific key suppression was removed.

Important macOS behavior:

- `Cmd+Shift+Space` is the clean start/stop path.
- `Enter` finishes early.
- `Esc` cancels.
- On macOS, `Enter` and `Esc` may still reach the frontmost app because selective
  global suppression is not implemented.

### `whisperflow_local/tray.py`

Switched from Windows `.ico` to macOS-friendly PNG icon usage.

### Deleted Obsolete Windows Files

Removed:

- `assets/icon.ico`
- `spikes/spike_enter.py`
- `spikes/spike_overlay.py`
- `tools/ico_from_png.py`
- `tools/make_icon.py`

These were Windows-specific or no longer needed after the macOS port.

### Updated Spikes

`spikes/spike_hotkey.py` now uses the macOS hotkey syntax:

```text
<cmd>+<shift>+<space>
```

`spikes/ab_cleanup.py` now compares local Unsloth cleanup models instead of old
Ollama candidates.

## How To Use It

### 1. Enter the repo

```bash
cd /Users/shawnvanbrunt/Developer/whisperflow-local
```

### 2. Install project dependencies

```bash
uv venv --python 3.11
uv pip install -e .
```

### 3. Grant macOS permissions

Grant Accessibility and Microphone permissions to the app that launches the
Python process.

During testing, the relevant apps were:

- WezTerm
- Codex
- Codex Computer Use

Where:

```text
System Settings -> Privacy & Security -> Accessibility
System Settings -> Privacy & Security -> Microphone
```

For Automation prompts, allow the launching app to control:

```text
System Events
TextEdit
```

### 4. Optional but recommended: start the persistent cleanup server

Print the exact command:

```bash
.venv/bin/python -m whisperflow_local cleanup-server-command
```

It prints a command like:

```bash
unsloth studio run \
  --model unsloth/Qwen3.5-4B-MTP-GGUF \
  --port 8888 \
  --host localhost \
  --disable-tools \
  --gguf-variant UD-Q4_K_XL
```

Run that command in another terminal.

Unsloth Studio prints an API key:

```text
sk-unsloth-...
```

Export it before running the app:

```bash
export UNSLOTH_API_KEY=sk-unsloth-...
```

The app deliberately does not commit this key to `config.yaml`.

If you do not start the server or do not export the key, the app falls back to
direct `unsloth` CLI cleanup. That works, but it is slower because it does not
keep the model warm as efficiently.

### 5. Run health checks

```bash
.venv/bin/python -m whisperflow_local doctor
```

Expected with server and key:

```text
doctor PASS
openai-compatible: default -> unsloth/Qwen3.5-4B-MTP-GGUF at http://localhost:8888/v1
```

Expected without server/key but with fallback available:

```text
doctor PASS
openai-compatible: server unavailable (...); fallback available
```

### 6. Run selftest

```bash
.venv/bin/python -m whisperflow_local selftest
```

This opens TextEdit, runs the full pipeline, pastes the cleaned result, verifies
the text, and closes the temporary TextEdit document without saving.

Expected:

```text
SELFTEST PASS
```

### 7. Run the live app

```bash
.venv/bin/python -m whisperflow_local run
```

Use:

```text
Cmd+Shift+Space
```

Flow:

1. Press `Cmd+Shift+Space`.
2. Speak.
3. Press `Cmd+Shift+Space` again to stop.
4. Wait for STT and cleanup.
5. Cleaned text is pasted into the focused field.

Other controls while recording:

- `Enter`: finish early.
- `Esc`: cancel.

On macOS, those keys may also reach the frontmost app. The hotkey is the safest
start/stop path.

## Verification Already Performed

The following checks passed during the port.

### Dependency install

```bash
uv pip install -e .
```

Passed after moving to the macOS dependency set.

### Python compile

```bash
PYTHONPYCACHEPREFIX=/tmp/whisperflow-pycache .venv/bin/python -m compileall whisperflow_local spikes
```

Passed.

### Diff whitespace

```bash
git diff --check
```

Passed.

### Windows/CUDA cleanup scan

Searched for active Windows/CUDA leftovers outside `.venv` and `.git`, including
terms like:

- `Windows`
- `Win32`
- `cuda`
- `faster-whisper`
- `pywin32`
- `win32gui`
- `winsound`
- `.ico`
- `large-v3-turbo`

No active matches remained.

### STT verification

MLX STT successfully transcribed the bundled sample audio.

Observed transcript:

```text
I'm so like I was thinking you know maybe we could us ship the the feature tomorrow morning if that works for everyone.
```

This proves the MLX STT path works locally on this Mac.

### Direct Unsloth fallback verification

Direct CLI cleanup worked.

Input:

```text
um so like I was thinking you know maybe we could uh ship the the feature tomorrow morning if that works for everyone
```

Output:

```text
So, I was thinking maybe we could ship the feature tomorrow morning if that works for everyone.
```

### Unsloth Studio server verification

Started:

```bash
unsloth studio run --model unsloth/Qwen3.5-4B-MTP-GGUF --gguf-variant UD-Q4_K_XL --port 8888 --host 127.0.0.1 --disable-tools
```

Unsloth Studio reported:

```text
Hardware detected: MLX - Apple Silicon (arm64)
Model loaded: unsloth/Qwen3.5-4B-MTP-GGUF (UD_Q4_K_XL)
OpenAI / Anthropic SDK base URL: http://127.0.0.1:8888/v1
```

Then:

```bash
UNSLOTH_API_KEY=sk-unsloth-... .venv/bin/python -m whisperflow_local doctor
```

Passed.

Then:

```bash
UNSLOTH_API_KEY=sk-unsloth-... .venv/bin/python -m whisperflow_local selftest
```

Passed.

The generated key was not written into the repo.

### Fallback verification after stopping server

After stopping Unsloth Studio:

```bash
.venv/bin/python -m whisperflow_local doctor
```

Passed by confirming fallback was available.

```bash
.venv/bin/python -m whisperflow_local selftest
```

Passed using direct Unsloth CLI fallback.

### Live app smoke test

Started:

```bash
.venv/bin/python -m whisperflow_local run
```

The app stayed running without immediate startup errors. It was then stopped
manually so no background test process remained.

## Current Git State

At the time of this handoff, the worktree is intentionally dirty with the macOS
port changes. Nothing has been committed yet.

Important changed areas:

- `.gitignore`
- `README.md`
- `CLAUDE.md`
- `PLAN.md`
- `PLAN-REVIEW-LOG.md`
- `docs/architecture.html`
- `config.yaml`
- `pyproject.toml`
- `whisperflow_local/*.py`
- `spikes/*.py`

Important new file:

```text
whisperflow_local/clipboard.py
```

Important removed files:

```text
assets/icon.ico
spikes/spike_enter.py
spikes/spike_overlay.py
tools/ico_from_png.py
tools/make_icon.py
```

Recommended next git step:

```bash
git add .
git commit -m "Port whisperflow-local to macOS Apple Silicon"
```

## What Remains To Test

The core macOS pipeline is implemented and verified, but these are the next
things to test before calling it product-polished.

### 1. Real live dictation in daily apps

Test in:

- TextEdit
- Notes
- Chrome text fields
- Slack/Discord-style Electron apps
- Terminal prompts where paste behavior matters
- Long text fields
- Multi-line fields

Things to watch:

- Does the hotkey fire reliably?
- Does the overlay avoid stealing focus?
- Does text paste into the right field?
- Does focus safety abort correctly if you switch apps while processing?
- Does the clipboard restore correctly?

### 2. Latency with and without Unsloth Studio

Measure:

- Direct CLI fallback latency.
- Warm Unsloth Studio server latency.
- First request after server startup.
- Cleanup latency for short, medium, and long dictations.

The server path is expected to feel much better because the model stays warm.

### 3. Long dictations

The config allows up to 5 minutes:

```yaml
audio:
  max_seconds: 300
```

Test:

- 30 seconds
- 1 minute
- 3 minutes
- 5 minutes

Watch for:

- STT latency.
- Cleanup truncation.
- Runaway cleanup guard.
- Memory pressure.
- Overlay responsiveness.

### 4. Permission UX

The app currently relies on macOS prompts and docs.

Could improve:

- First-run permission checker.
- Friendlier messages when Accessibility is missing.
- Friendlier messages when Microphone is missing.
- A `.app` wrapper so permissions attach to the app instead of WezTerm/Codex.

### 5. Packaging

Likely next polish step:

- Create a real macOS `.app` bundle.
- Give it a stable bundle identifier.
- Attach Accessibility/Microphone permissions to the bundle.
- Use a real app icon.
- Optionally package with `pyinstaller`, `briefcase`, or a lightweight wrapper.

### 6. Autostart

LaunchAgent support exists, but should be tested in a fresh login cycle:

```bash
.venv/bin/python -m whisperflow_local install-autostart
```

Then:

1. Log out.
2. Log back in.
3. Confirm the tray app starts.
4. Confirm permissions still work.
5. Confirm the cleanup server strategy is acceptable at login.

Open question:

Should autostart also start Unsloth Studio, or should that remain a separate
manual/performance mode?

### 7. Cleanup server lifecycle

Right now, the app can use the server if it is already running, but it does not
own the server lifecycle.

Possible next-level work:

- Add `start-cleanup-server`.
- Add `stop-cleanup-server`.
- Persist the generated API key securely.
- Detect server readiness.
- Auto-fallback to CLI if server startup fails.
- Show tray status for cleanup runtime: `server`, `fallback`, or `unavailable`.

### 8. Provider naming cleanup

Current provider names:

```yaml
provider: "openai-compatible"
fallback_provider: "unsloth-cli"
```

Backward-compatible alias:

```yaml
provider: "omlx"
```

This is intentional for now. Long term, `omlx` can be deprecated once configs and
docs no longer need compatibility with the earlier intermediate implementation.

### 9. Better live app shutdown

During smoke tests, the tray app did not exit cleanly from Ctrl-C through the
PTY and was stopped with a targeted process kill. This is not necessarily a
product bug because the app is a Qt tray process, but it is worth improving.

Possible improvement:

- Install a signal handler that calls `QApplication.quit()`.

### 10. More robust insertion target detection

Current focus safety checks the frontmost process PID. That is a good macOS v1
guard, but it is not as precise as control-level caret tracking.

Future improvement:

- Use Accessibility APIs to capture focused element information.
- Verify the same focused element before paste.
- Better support apps with multiple text fields in the same process.

## Known Caveats

### Enter/Esc behavior

On macOS, Enter and Esc are detected globally but are not selectively suppressed.
They may also reach the frontmost app.

Best user workflow:

```text
Use Cmd+Shift+Space to start and stop dictation.
```

### Server API key

Unsloth Studio prints a new `sk-unsloth-*` key. That key must be exported:

```bash
export UNSLOTH_API_KEY=sk-unsloth-...
```

The key should not be committed.

### Direct fallback is slower

The direct `unsloth-cli` fallback is verified and useful, but it is not the best
latency path for daily use. The persistent Unsloth Studio server is the better
experience.

### Project MLX pin is intentional

The machine has newer MLX installs elsewhere, but the app currently pins MLX in
the project venv. Do not casually upgrade MLX without re-testing
`lightning-whisper-mlx` and the STT sample.

## Recommended Next Steps

1. Commit the macOS port.
2. Do a live dictation session in TextEdit, Notes, Chrome, and an Electron app.
3. Measure latency with Unsloth Studio server running.
4. Decide whether the app should own the cleanup server lifecycle.
5. Add a `.app` wrapper for stable macOS permissions.
6. Add signal handling for cleaner Ctrl-C shutdown.
7. Improve focus checking from process-level to focused-element-level using macOS
   Accessibility APIs.

## Summary For The Next Model

This was a full platform port, not a superficial compatibility patch.

The codebase moved from a Windows/CUDA dictation prototype to a macOS Apple
Silicon local dictation app. The STT path now runs through MLX on Metal. The
cleanup path now uses the local Unsloth ecosystem already installed on this
machine, with a fast persistent server path and a working CLI fallback. The
insertion, clipboard, overlay, autostart, docs, config, and tests were all moved
to macOS concepts.

The most important proof points are:

- `doctor PASS`
- `selftest PASS`
- MLX transcription works
- Unsloth Studio cleanup works
- Direct Unsloth fallback works
- TextEdit insertion is verified
- Windows/CUDA references are removed from active code/docs

The repo is ready for a commit and then real-world product polishing.
