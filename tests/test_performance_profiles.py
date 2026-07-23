import unittest

from whisperflow_local.performance_profiles import resolve_profile, streaming_gate


class PerformanceProfileTests(unittest.TestCase):
    def test_batch_remains_default_until_gate_passes(self):
        self.assertFalse(resolve_profile("instant").streaming)
        self.assertTrue(resolve_profile("instant", streaming_gate_passed=True).streaming)

    def test_streaming_gate_requires_latency_quality_and_memory(self):
        values = dict(batch_p95_ms=1000, candidate_p95_ms=850, quality_parity=True,
                      peak_memory_mb=1000, memory_budget_mb=2000)
        self.assertTrue(streaming_gate(**values))
        self.assertFalse(streaming_gate(**{**values, "candidate_p95_ms": 950}))
        self.assertFalse(streaming_gate(**{**values, "quality_parity": False}))
        self.assertFalse(streaming_gate(**{**values, "peak_memory_mb": 3000}))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_profile("turbo-magic")


if __name__ == "__main__":
    unittest.main()
