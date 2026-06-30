# Plan Review Log: 100% Local WhisperFlow Clone
Act 1 (grill) complete — plan locked with the user. MAX_ROUNDS=5.

## Round 1 — Codex
- [High] Locks `large-v3-turbo` though research marks STT perf unverified. Fix: benchmark turbo vs distil-large-v3 vs CPU fallback on target HW before building.
- [High] Open hotkey collision; core UX may be flaky. Fix: pick + test a full chord now (e.g. Ctrl+Win+Space), configurable.
- [High] Assumes focused field stays correct after processing delay; user can alt-tab → text leaks into wrong app. Fix: capture foreground window/control at stop, verify still matches before insert.
- [High] Clipboard restore mentions only plain text; can destroy rich formats / race clipboard managers. Fix: preserve all formats via Win32, or make paste opt-in with typing fallback default.
- [High] No reentrancy policy; 2nd toggle during STT/cleanup corrupts state / pastes stale output. Fix: explicit states, ignore/cancel input during PROCESSING.
- [High] Too much work in sounddevice callback; PortAudio callbacks must not allocate/block. Fix: ring-buffer raw audio, push only scalar RMS/status from callback.
- [Medium] "No cloud calls anywhere" false — first-run model pulls from HF/Ollama are cloud. Fix: offline bootstrap pre-downloads models, then run local_files_only.
- [Medium] Trusts LLM cleanup too much; can add content / obey transcript prompt-injection / change meaning. Fix: transcript-only editing prompt, disable thinking, cap output vs input, reject suspicious expansion.
- [Medium] "Drop low-confidence STT" has no threshold. Fix: specify duration, RMS, no_speech_prob, logprob, language-prob thresholds.
- [Medium] Paste/type may fail into elevated apps, RDP, games, protected browser fields, UAC. Fix: document unsupported targets, detect foreground integrity level.
- [Medium] Warmup can monopolize VRAM / fail if other GPU load. Fix: startup health checks, load timeout, smaller-model fallback, degraded-mode status.
- [Medium] Only considers focus-steal, not hit-test/z-order. Fix: no-activate + click-through (transparent hit-test), or keep pill outside typing area.
- [Medium] No observability beyond UI. Fix: log per-request timings, model state, audio dur/RMS, STT confidence, token counts, paste success/fail, traces — locally.
- [Low] tkinter "fallback" doesn't solve non-activating overlay equivalently. Fix: remove tkinter from v1 or define degraded behavior.
- [Low] "Single general cleanup" — make explicit it's transcript-only, not contextual tone (a stated WhisperFlow differentiator).
- [Low] Stack lacks dependency pins, CUDA/cuDNN versions, install validation. Fix: pinned pyproject + a `doctor` command (mic, CUDA, Ollama, hotkey, overlay, clipboard).

VERDICT: REVISE

### Claude's response
Accepted nearly all — they're sound. Changes to PLAN.md:
- **Hotkey:** resolved open question → default `Ctrl+Alt+Space` (avoids Win-key reserved combos + virtual-desktop shortcuts), configurable.
- **State machine:** added explicit IDLE→RECORDING→PROCESSING states; taps during PROCESSING ignored (no reentrancy).
- **Focus safety:** capture foreground window handle at stop; abort paste (fallback: type or notify) if focus changed before insert. Prevents wrong-app leak.
- **Audio callback:** ring-buffer raw frames, callback pushes only scalar RMS — no allocation/blocking.
- **Clipboard:** save/restore with a settle delay; preserve text format, document rich-format limitation; type() fallback path retained.
- **Offline nuance:** reworded — RUNTIME is 100% local/offline; one-time SETUP bootstrap pre-downloads models, then `local_files_only`. No cloud at dictation time.
- **Cleanup guards:** transcript-only edit prompt, thinking disabled, output capped vs input length, reject suspicious expansion (anti prompt-injection).
- **STT thresholds:** defined (min duration, RMS floor, no_speech_prob, avg logprob).
- **Overlay:** non-activating + click-through (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT).
- **Robustness:** startup health check (VRAM/CUDA/Ollama/mic) + degraded-mode status; max-recording safety cutoff already present.
- **Observability:** local structured log of per-stage timings + STT confidence + paste success/fail.
- **`doctor` command + pinned deps** (pyproject + lock; CUDA/cuDNN notes).
- **Benchmark gate:** added a pre-build mini-benchmark (turbo vs distil-large-v3) on the 5090 — also closes the research "unverified STT" gap.
- **Dropped tkinter fallback** from v1 (can't match non-activating overlay) — PySide6 only.
- Rejected nothing outright; "per-app tone" stays v2, now stated explicitly as transcript-only in v1.

## Round 2 — Codex
Confirmed round-1 fixes landed. Remaining:
- [High] Verifies only top-level HWND; focus can move to another control in same window → wrong control. Fix: re-verify focused control/UIA caret target, not just HWND.
- [High] Clipboard-paste default still clobbers non-text clipboard (only plain text preserved). Fix: detect non-text/rich clipboard → switch to type-fallback before modifying clipboard.
- [High] Taps ignored during PROCESSING but no timeout/recovery if Whisper/Ollama hangs. Fix: per-stage timeouts + cancellation/error transitions + guaranteed return to IDLE.
- [Medium] Ring buffer has no overflow behavior. Fix: size from max duration, visible fail/auto-stop on overflow, no silent truncation.
- [Medium] No sample rate/channels/dtype/resampling defined. Fix: 16kHz mono float32 (or explicit resample) before faster-whisper.
- [Medium] Logs don't state whether dictated text is logged. Fix: metadata-only default, redact payloads, rotate, opt-in transcript logging.
- [Medium] "Thinking disabled" may be no-op per model/API. Fix: explicit model-specific gen options, unsupported → doctor warning.
- [Medium] Model pinning location/drift unspecified. Fix: pin exact model IDs/revisions/checksums in config, validate in setup/doctor.
- [Low] Qt/pynput cross-thread underspecified. Fix: queued Qt signals/timers for all cross-thread UI updates; hotkey callbacks never touch UI directly.

VERDICT: REVISE

### Claude's response
Accepted all 8 — all correct, all cheap to specify now. PLAN.md updated:
- Focus check upgraded to control/caret-level re-verify (pragmatic: HWND + focused-control/caret via GUITHREADINFO; type-fallback if mismatch).
- Clipboard: detect non-text/rich contents first → route to type-fallback before touching clipboard; else save/set/paste/restore plain text.
- State machine: per-stage timeouts (STT, cleanup) + cancellation + guaranteed return to IDLE on hang/error.
- Ring buffer: sized from max-recording-duration; visible auto-stop on overflow, no silent truncation.
- Audio format pinned: 16 kHz mono float32 (resample if device differs).
- Log privacy: metadata-only by default, transcript logging opt-in, payload redaction, rotation.
- Cleanup gen options made model-specific + explicit; unsupported options surface as doctor warnings.
- Model pinning: exact IDs/revisions/checksums in config, validated by setup + doctor.
- Qt threading: all cross-thread UI via queued signals/timers; hotkey/audio callbacks never touch PySide directly.

## Round 3 — Codex
All round-2 findings confirmed addressed. **Must-fix before implementation: None — plan sound enough to start.**
Implementation-detail notes:
- Make the overlay-flags spike the FIRST step, not a late integration test.
- Test hotkey in Chrome, Electron, terminals, IME fields before building around it.
- `doctor` should verify Ollama via localhost + warn if exposed beyond loopback.
- `type()` fallback may be slow/imperfect for long Unicode — cap + log fallback use.

VERDICT: APPROVED

### Claude's response
Folded the concrete notes into PLAN.md: added a "Build sequence (de-risk first)" block (overlay spike → hotkey spike → linear loop), the doctor localhost/loopback check, and the type()-fallback cap+log. Plan converged in 3 rounds.
