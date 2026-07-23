from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WritingMode:
    key: str
    label: str
    instruction: str


MODES = {
    "natural": WritingMode("natural", "Natural", "Preserve the speaker's casual tone."),
    "polished": WritingMode("polished", "Polished", "Use concise professional prose without adding ideas."),
    "verbatim": WritingMode("verbatim", "Verbatim", "Only add punctuation and capitalization; preserve every word."),
    "email": WritingMode("email", "Email", "Format as a clear email while preserving meaning and details."),
}


def resolve_writing_mode(default: str, bundle_id: str | None, overrides: dict[str, str]) -> WritingMode:
    key = overrides.get(bundle_id or "", default)
    try:
        return MODES[key]
    except KeyError as exc:
        raise ValueError(f"unknown writing mode: {key}") from exc
