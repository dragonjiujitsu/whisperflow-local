import json
import unittest
from pathlib import Path

from whisperflow_local.evaluation import evaluate_cleanup


class EvaluationCorpusTests(unittest.TestCase):
    def test_all_synthetic_cases_match_expected_preservation_result(self):
        path = Path(__file__).parent / "fixtures/evaluation/cleanup_cases.json"
        for case in json.loads(path.read_text()):
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    evaluate_cleanup(case["source"], case["candidate"]).safe,
                    case["safe"],
                )


if __name__ == "__main__": unittest.main()
