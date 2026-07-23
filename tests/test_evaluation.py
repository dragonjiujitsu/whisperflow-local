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

    def test_configured_single_word_name_is_protected(self):
        source = "Send the update to Kaden tomorrow"
        candidate = "Send the update to Caden tomorrow."
        result = evaluate_cleanup(source, candidate, protected_terms=["Kaden"])
        self.assertFalse(result.safe)
        self.assertEqual(result.missing_tokens, ("Kaden",))
        self.assertEqual(
            guarded_cleanup(source, candidate, protected_terms=["Kaden"]), source
        )

    def test_configured_term_absent_from_source_is_not_required(self):
        result = evaluate_cleanup(
            "Send the update tomorrow", "Send the update tomorrow.",
            protected_terms=["Kaden"],
        )
        self.assertTrue(result.safe)

    def test_configured_term_uses_canonical_spelling_and_word_boundary(self):
        source = "send kaden the update"
        self.assertTrue(
            evaluate_cleanup(
                source, "Send Kaden the update.", protected_terms=["Kaden"]
            ).safe
        )
        self.assertFalse(
            evaluate_cleanup(
                source, "Send Kadenish the update.", protected_terms=["Kaden"]
            ).safe
        )


if __name__ == "__main__":
    unittest.main()
