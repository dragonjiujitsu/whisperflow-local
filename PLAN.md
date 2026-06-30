# Plan: 100% Local WhisperFlow Clone (Windows dictation tool)
_Locked via grill — by Claude + Chase. Revised after Codex round 1._

## Goal
A Windows dictation app whose RUNTIME is fully offline and beats built-in Voice Typing by adding a local AI rewrite pass. Toggle a hotkey, a slick non-activating pill appears and reacts to your voice, you speak, toggle off, and clean corrected text (filler removed, grammar/punctuation fixed, meaning + voice preserved) is auto-inserted into whatever text field had focus. STT and the cleanup LLM both run locally on-device — no cloud calls at dictation time. (One-time SETUP downloads the models; see Offline model.) Built as a worked example for a YouTube video whose REAL deliverable is the *process* (deep-research → grill → plan → Claude Code executes), not the code's pedagogy.

## Approach
1. **Capture** — `sounddevice` InputStream at **16 kHz mono float32** (explicit resample if the device default differs) — the format faster-whisper expects. The PortAudio callback does NO allocation/blocking: it writes raw frames into a preallocated ring buffer (sized from the max-recording-duration) and pushes only a scalar RMS value onto a thread-safe queue for the overlay. On ring-buffer overflow: visible auto-stop, never silent truncation.
2. **Hotkey + state machine** — `pynput` `GlobalHotKeys` on `Ctrl+Alt+Space` (tap; configurable). Explicit states: `IDLE → RECORDING → PROCESSING → IDLE`. 1st tap (IDLE) = start + show overlay; 2nd tap (RECORDING) = stop, hide overlay, enter PROCESSING. Taps during PROCESSING are ignored (no reentrancy / no stale-output corruption). **Per-stage timeouts** (STT, cleanup) + cancellation/error transitions guarantee a return to IDLE if Whisper/Ollama hangs — the app never wedges. Configurable max-recording-duration safety cutoff auto-stops a forgotten session.
3. **STT** — `faster-whisper large-v3-turbo` on CUDA (RTX 5090), speed-prioritized. Reject low-confidence output via thresholds: min audio duration, RMS floor, `no_speech_prob`, average logprob. (See Benchmark gate before locking the model.)
4. **Cleanup** — local Ollama `qwen2.5:7b-instruct`, kept warm via `keep_alive`. Single general TRANSCRIPT-ONLY cleanup prompt (externalized in config): edit the transcript, do not add content, do not follow instructions inside the transcript (anti prompt-injection), output length capped relative to input; reject + fall back to raw transcript if output suspiciously expands. Generation options are **model-specific and explicit** (e.g. `think:false` where supported); unsupported options surface as `doctor` warnings rather than silently no-op. 3B is a one-line config fallback if latency disappoints.
5. **Focus-safe insert** — capture both the foreground window handle AND the focused control / caret target (via `GUITHREADINFO`) at STOP time. After processing, re-verify the same control still has focus before inserting; if focus moved (different app OR different control in the same window), abort paste and notify rather than leak text into the wrong field. Insertion = clipboard-paste, but FIRST inspect the current clipboard: if it holds non-text / rich content, route to the `type()` fallback instead of clobbering it. Otherwise save plain-text clipboard → set cleaned text → `Ctrl+V` via `pynput` → restore after a short settle delay. (Rich-clipboard preservation is out of scope; we detect-and-avoid instead.) `Controller.type()` is also the config-flag fallback for paste-hostile apps.
6. **Overlay** — PySide6 always-on-top, **non-activating + click-through** (`WS_EX_NOACTIVATE | WS_EX_TRANSPARENT`) frameless pill with a live waveform/level animation driven by the RMS queue. Never steals focus, never intercepts clicks. (tkinter dropped from v1 — cannot match non-activating overlay behavior.)
7. **Offline model + warmup** — one-time SETUP bootstrap pre-downloads the Whisper + Ollama models, pinned to **exact model IDs/revisions (and checksums where available)** in config and validated by setup + `doctor` to prevent version/hash drift; runtime then uses `local_files_only` / local model checks (no network at dictation time). On launch: startup health check (CUDA available, VRAM free, Ollama up, mic present, models present + matching pin) → load Whisper into VRAM + ping Ollama keep-alive. On failure, smaller-model/CPU fallback + visible degraded-mode status.
8. **Threading** — audio capture (callback thread) / overlay (main/UI thread) / STT+cleanup (worker thread) so the UI never freezes. ALL cross-thread UI updates go through **queued Qt signals/timers** — hotkey and audio callbacks never touch PySide widgets directly.
9. **Observability** — local structured log, **metadata-only by default**: per-stage timings (record/STT/cleanup/insert), audio duration + RMS, STT confidence, cleanup token counts, paste success/failure, redacted exception traces. Logging the actual transcript text is **opt-in**; logs rotate.

## Key decisions & tradeoffs
- **Runtime 100% local, hard constraint.** Cleanup runs on Ollama locally; cloud Haiku explicitly ruled out. This is the entire reason to clone vs. use WhisperFlow (cloud-only, vendor-confirmed). Setup-time model download is the one allowed network step.
- **Speed is the priority metric.** Drove `large-v3-turbo` over `large-v3`, and a 7B (vs larger) cleanup model. The cleanup LLM — not STT — is the latency bottleneck on a 5090.
- **Toggle over hold-to-talk** (user choice). Cost: explicit recording-state indicator (the overlay) + max-duration safety stop + reentrancy guard.
- **PySide6 overlay** (user wants it to look cool; video hero shot). Cost: heavy dep + non-activating/click-through window complexity. tkinter dropped from v1.
- **Clipboard-paste over type-it-out**, gated by focus re-verification. Instant block insert (speed-first); type() fallback for paste-hostile apps.
- **Single general cleanup, transcript-only.** Predictable latency, smaller failure + injection surface. Contextual/per-app tone = v2.
- **Modular file layout** for engineering quality (debuggability, maintainability), NOT teachability.
- **Stack:** Python 3.11+, `uv`, pinned `pyproject.toml` + lock, CUDA faster-whisper (cuDNN/cuBLAS notes documented), Ollama. A `doctor` command validates mic, CUDA, Ollama (incl. that it's reached via localhost/loopback — warn if exposed beyond), hotkey, overlay, clipboard, model pins.

## Build sequence (de-risk first)
1. **Spike the overlay flags FIRST** — prove `WS_EX_NOACTIVATE | WS_EX_TRANSPARENT` on Win 11 (non-activating + click-through) before building anything around it. Paste correctness depends on it.
2. **Spike the hotkey** — confirm `Ctrl+Alt+Space` fires reliably across Chrome, Electron apps, terminals, and IME-enabled fields before wiring the state machine.
3. Then the linear loop: capture → STT → cleanup → focus-safe insert → integrate overlay → doctor + observability.
- `type()` fallback may be slow/imperfect for long Unicode — acceptable v1, but cap its use and log every fallback so failures are visible.

## Risks / open questions
- **Overlay focus-steal / click interception (critical).** Must verify `WS_EX_NOACTIVATE | WS_EX_TRANSPARENT` on Win 11 before building further — paste correctness depends on it.
- **Hotkey reliability.** `Ctrl+Alt+Space` chosen to avoid Win-key reserved combos; still must confirm `GlobalHotKeys` fires reliably and no app/IME steals it. Configurable.
- **Insertion into protected targets.** Elevated apps, RDP, anti-cheat games, protected browser fields, UAC prompts will reject synthetic input — documented as unsupported; best-effort foreground integrity-level detection.
- **Clipboard managers** may race the save/restore even with a settle delay — type() fallback is the escape hatch.
- **faster-whisper CUDA setup** on Windows (cuDNN/cuBLAS DLLs) is a known friction point — explicit setup notes + `doctor` check.
- **Empty/hallucinated STT** on silence — covered by the confidence thresholds (no paste on fail).
- **Viewer hardware gap.** Plan is tuned to a 5090; document model-size fallbacks for reproducibility.

## Pre-build benchmark gate
Before locking the STT model, run a quick on-device (5090) benchmark of `large-v3-turbo` vs `distil-large-v3` (and note a CPU fallback) measuring end-to-end utterance latency + subjective accuracy on real dictation. Closes the research brief's "unverified STT performance" gap and confirms the speed-first pick empirically. Default stays `large-v3-turbo` unless the benchmark says otherwise.

## Out of scope (v1)
Per-app / contextual tone adaptation; system-tray icon; hold-to-talk mode; streaming/real-time transcription; cross-platform (Windows only); installer/packaging; custom vocabulary; multi-language; rich-clipboard-format preservation.
