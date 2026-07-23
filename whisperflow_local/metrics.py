"""Content-free pipeline metrics.

Only durations, coarse outcomes, and operational flags are accepted here.
Audio and transcript content deliberately have no representation in the schema.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from threading import Lock
from typing import Iterable


@dataclass(frozen=True)
class PipelineMetric:
    session_id: int
    audio_seconds: float
    stt_ms: float
    cleanup_ms: float
    insert_ms: float
    total_ms: float
    outcome: str
    stt_warm: bool
    cleanup_warm: bool
    peak_memory_mb: float = 0.0
    backend_health: str = "unknown"

    def as_log_fields(self) -> dict[str, object]:
        return asdict(self)


class MetricsCollector:
    """Bounded in-memory metrics with optional metadata-only logger output."""

    def __init__(self, logger=None, max_records: int = 500) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self._logger = logger
        self._max_records = max_records
        self._records: list[PipelineMetric] = []
        self._lock = Lock()

    def observe(self, metric: PipelineMetric) -> None:
        with self._lock:
            self._records.append(metric)
            if len(self._records) > self._max_records:
                del self._records[: len(self._records) - self._max_records]
        if self._logger is not None:
            self._logger.info(
                "pipeline_metric session_id=%s audio_s=%.3f stt_ms=%.1f "
                "cleanup_ms=%.1f insert_ms=%.1f total_ms=%.1f outcome=%s "
                "stt_warm=%s cleanup_warm=%s peak_memory_mb=%.1f backend_health=%s",
                metric.session_id,
                metric.audio_seconds,
                metric.stt_ms,
                metric.cleanup_ms,
                metric.insert_ms,
                metric.total_ms,
                metric.outcome,
                metric.stt_warm,
                metric.cleanup_warm,
                metric.peak_memory_mb,
                metric.backend_health,
            )

    def snapshot(self) -> tuple[PipelineMetric, ...]:
        with self._lock:
            return tuple(self._records)

    def summary(self, outcome: str | None = None) -> dict[str, float | int]:
        records: Iterable[PipelineMetric] = self.snapshot()
        if outcome is not None:
            records = (item for item in records if item.outcome == outcome)
        values = sorted(item.total_ms for item in records)
        if not values:
            return {"count": 0}
        return {
            "count": len(values),
            "p50_total_ms": median(values),
            "p95_total_ms": _percentile(values, 0.95),
            "max_total_ms": values[-1],
        }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        raise ValueError("cannot calculate a percentile of no values")
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between zero and one")
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
