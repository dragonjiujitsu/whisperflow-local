from __future__ import annotations

import unittest

from whisperflow_local.metrics import MetricsCollector, PipelineMetric


def metric(session_id: int, total: float, outcome: str = "inserted") -> PipelineMetric:
    return PipelineMetric(
        session_id=session_id,
        audio_seconds=2.0,
        stt_ms=total * 0.5,
        cleanup_ms=total * 0.4,
        insert_ms=total * 0.1,
        total_ms=total,
        outcome=outcome,
        stt_warm=True,
        cleanup_warm=True,
    )


class MetricsTests(unittest.TestCase):
    def test_schema_cannot_hold_content(self) -> None:
        fields = metric(1, 100).as_log_fields()
        self.assertNotIn("transcript", fields)
        self.assertNotIn("audio", fields)
        self.assertNotIn("cleaned_text", fields)
        self.assertEqual(fields["audio_seconds"], 2.0)

    def test_collector_is_bounded(self) -> None:
        collector = MetricsCollector(max_records=2)
        for index in range(3):
            collector.observe(metric(index, 100 + index))
        self.assertEqual(
            [item.session_id for item in collector.snapshot()], [1, 2]
        )

    def test_summary_reports_p50_and_p95(self) -> None:
        collector = MetricsCollector()
        for index, total in enumerate((100.0, 200.0, 300.0, 400.0, 500.0)):
            collector.observe(metric(index, total))
        summary = collector.summary()
        self.assertEqual(summary["count"], 5)
        self.assertEqual(summary["p50_total_ms"], 300.0)
        self.assertAlmostEqual(summary["p95_total_ms"], 480.0)
        self.assertEqual(summary["max_total_ms"], 500.0)

    def test_summary_filters_outcomes(self) -> None:
        collector = MetricsCollector()
        collector.observe(metric(1, 100, "inserted"))
        collector.observe(metric(2, 900, "timeout"))
        self.assertEqual(collector.summary("inserted")["count"], 1)
        self.assertEqual(collector.summary("timeout")["p50_total_ms"], 900)

    def test_empty_summary_is_explicit(self) -> None:
        self.assertEqual(MetricsCollector().summary(), {"count": 0})


if __name__ == "__main__":
    unittest.main()
