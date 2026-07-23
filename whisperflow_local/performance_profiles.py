from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerformanceProfile:
    name: str
    model: str
    batch_size: int
    streaming: bool


PROFILES = {
    "instant": PerformanceProfile("instant", "distil-large-v3", 12, False),
    "quality": PerformanceProfile("quality", "large-v3", 8, False),
}


def resolve_profile(name: str, *, streaming_gate_passed: bool = False) -> PerformanceProfile:
    try:
        selected = PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown performance profile: {name}") from exc
    if selected.name == "instant" and streaming_gate_passed:
        return PerformanceProfile(selected.name, selected.model, selected.batch_size, True)
    return selected


def streaming_gate(
    *, batch_p95_ms: float, candidate_p95_ms: float,
    quality_parity: bool, peak_memory_mb: float, memory_budget_mb: float,
) -> bool:
    """Promotion requires >=10% p95 gain, exact quality parity, and memory budget."""
    if min(batch_p95_ms, candidate_p95_ms, memory_budget_mb) <= 0:
        raise ValueError("latency and memory budget values must be positive")
    return (
        quality_parity
        and candidate_p95_ms <= batch_p95_ms * 0.90
        and peak_memory_mb <= memory_budget_mb
    )
