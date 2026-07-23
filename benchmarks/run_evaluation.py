from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from whisperflow_local.evaluation import evaluate_cleanup


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic cleanup preservation corpus")
    parser.add_argument("--fixture", type=Path, default=ROOT / "tests/fixtures/evaluation/cleanup_cases.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.fixture.read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        result = evaluate_cleanup(case["source"], case["candidate"])
        rows.append({
            "id": case["id"], "expected_safe": case["safe"], "actual_safe": result.safe,
            "pass": result.safe is case["safe"], "missing_token_count": len(result.missing_tokens),
            "filler_removed": result.filler_removed, "punctuation_added": result.punctuation_added,
            "paragraph_intent_preserved": result.paragraph_intent_preserved,
        })
    report = {
        "schema": 1, "fixture_kind": "synthetic", "case_count": len(rows),
        "passed": sum(row["pass"] for row in rows), "failed": sum(not row["pass"] for row in rows),
        "rows": rows,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__": raise SystemExit(main())
