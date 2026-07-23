# Native macOS product verification

Date: 2026-07-10

Machine: Apple Silicon arm64, macOS 26.5.2

Bundle: `build/WhisperFlow Local.app` (`com.shawnvanbrunt.whisperflow-local`, 0.2.0)

## Release gates

| Gate | Evidence | Result |
|---|---|---|
| Static compile | `PYTHONPYCACHEPREFIX=/tmp/whisperflow-pycache .venv/bin/python -m compileall -q whisperflow_local tests benchmarks packaging` | Pass |
| Automated suite | `.venv/bin/python -m pytest -q` | Pass: 106 tests + 10 subtests |
| Diff hygiene | `git diff --check` | Pass |
| Environment health | `.venv/bin/python -m whisperflow_local doctor` | Pass; microphone and Accessibility authorized; preferred cleanup unavailable is explicitly degraded with direct local fallback available |
| Source E2E | `.venv/bin/python -m whisperflow_local selftest` | Pass: sample → MLX STT → local cleanup → focus-safe TextEdit paste |
| Batch benchmark | `benchmarks/results/batch-m5-max.json` | Pass: 2/10/60-second profiles, p50/p95, cold warmup, peak RSS; streaming not promoted |
| Evaluation corpus | `.venv/bin/python benchmarks/run_evaluation.py` | Pass: 5/5 synthetic cases |
| Privacy audit | `.venv/bin/python packaging/privacy_audit.py` | Pass: disabled history and ephemeral recovery persist no sentinel content |
| Bundle verification | `.venv/bin/python packaging/verify_bundle.py 'build/WhisperFlow Local.app'` | Pass: metadata, resources, arm64, MLX shaders, speech assets, strict signature |
| Clean-home shell | copied bundle with temporary empty `HOME` and deterministic smoke exit | Pass |
| Outside-repo bundle E2E | copied bundle under `/tmp`, `WHISPERFLOW_BUNDLE_SELFTEST=1` | Pass: packaged MLX/SciPy, app-owned offline model, cleanup, TextEdit insertion |

The frozen E2E emits a harmless Nuitka 2.7.11/SciPy 1.16 COBYLA post-load warning for an optimizer that is not used by dictation. Excluding `scipy.optimize` was tested and rejected because `scipy.signal` legitimately imports interpolation code that depends on it. Inference and the test exit status remain successful.

## Requirement evidence

- R1–R2: immutable session IDs, legal reducer transitions, cancellation tokens, stale completion rejection, timeout serialization, fail-closed sleep/wake and quit handling; covered by session, controller, cleanup-cancellation, and power-monitor tests.
- R3–R5: content-free stage metrics include p50/p95 support, peak memory and backend health; measured batch remains selectable and is the default; streaming cannot be promoted without the latency/quality/memory gate.
- R6–R10: signed-app-ready stable bundle, app-owned paths, onboarding, complete settings tabs, tray health, diagnostics, recovery, asynchronous warmup, explicit degraded fallback, and launch-at-login fixture.
- R11–R14: Accessibility element/window/app identity revalidation, native multi-type pasteboard transactions, focus-change recovery, and auto-submit disabled by default.
- R15–R16: Application Support/Caches/Logs/Keychain lifecycle, app-owned speech model, cleanup service ownership and local fallback; outside-repo offline model proof passes.
- R17–R18: inspectable vocabulary/replacements and per-app modes; history off by default with user-only file permissions, retention, inspection, export, delete-one API and delete-all UI; recovery is memory-only and expiring.
- R19–R20: protected names, numbers, dates, URLs, paths, code and paragraph structure; embedded-instruction regression case; no required cloud inference.
- AE1–AE7: covered by automated stale-session, focus identity, pasteboard, permission, fallback, evaluation, and disabled-history tests plus the TextEdit bundle E2E.

## Real-app insertion matrix

| Target | Evidence | Status |
|---|---|---|
| TextEdit (native rich text) | Source and copied-bundle E2E read back exact inserted text | Pass |
| Same-process different field/window | Fake native Accessibility identities and final-boundary revalidation | Pass (automated) |
| Rich/multi-item clipboard | Native pasteboard snapshot/change-count tests | Pass (automated) |
| Browser contenteditable | Chrome is installed; Computer Use service failed to start during this run | Environment-limited, not claimed as pass |
| Electron | Slack is not installed on this Mac | Environment-limited, not claimed as pass |
| VS Code | Installed; GUI automation unavailable during this run | Environment-limited, not claimed as pass |
| Terminal | Installed; GUI automation unavailable during this run | Environment-limited, not claimed as pass |

The non-TextEdit rows remain a concrete manual release checklist. The insertion implementation fails closed for any target whose focused Accessibility identity changes, and preserves the result in recovery and on the clipboard.

## Preservation

The repository was already dirty with the macOS port. No reset, checkout, commit, or unrelated-file overwrite was performed. New changes remain uncommitted for user review.
