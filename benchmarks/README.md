# Local pipeline benchmark

Run from the project virtual environment on the Mac being evaluated:

```bash
.venv/bin/python benchmarks/run_baseline.py --runs 5 --durations 2,10,60 \
  --output benchmarks/results/batch-m5-max.json
```

The runner uses the bundled synthetic spoken sample, records cold warmup and peak
RSS, then reports short/medium/long p50/p95 transcription, cleanup, and total latency.
It stores no audio or transcript content. Use `--output path.json` to retain a
machine-readable comparison locally.

The repeated fixture is appropriate for performance and memory characterization;
use distinct approved fixtures when measuring recognition quality. Record:

- machine and macOS version;
- model and quantization profile;
- cold first request separately from warm runs;
- p50 and p95 stage latency;
- peak resident memory and energy impact;
- whether the preferred cleanup server or fallback ran.

Do not use personal dictations as benchmark fixtures unless they were explicitly
approved for that purpose. Benchmark outputs are metadata-only by design.

Streaming remains disabled unless a candidate report shows final-text parity,
at least a 10% p95 latency improvement, and peak memory within the declared
budget. A protocol implementation alone is not promotion evidence.
