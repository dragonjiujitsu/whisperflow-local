import unittest

from whisperflow_local.evaluation import evaluate_cleanup, guarded_cleanup


class EvaluationTests(unittest.TestCase):
    def test_protected_tokens_block_damaging_cleanup(self):
        source = "Um send Jane Smith $1,240 to https://example.com/a and run `git status`."
        candidate = "Send Jane to example.com and run it."
        result = evaluate_cleanup(source, candidate)
        self.assertFalse(result.safe)
        self.assertEqual(guarded_cleanup(source, candidate), source)

    def test_safe_cleanup_measures_value(self):
        source = "Um visit https://example.com and uh confirm 2026-07-10"
        candidate = "Visit https://example.com and confirm 2026-07-10."
        result = evaluate_cleanup(source, candidate)
        self.assertTrue(result.safe)
        self.assertEqual(result.filler_removed, 2)
        self.assertTrue(result.punctuation_added)


if __name__ == "__main__":
    unittest.main()
