from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN_PATTERNS = (
    re.compile(r"https?://[^\s]+"),
    re.compile(r"(?:/[^\s/]+){2,}"),
    re.compile(r"\b\d+(?:[.,:/-]\d+)*\b"),
    re.compile(r"`[^`]+`"),
    re.compile(r"\b[A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*)+\b"),
)


@dataclass(frozen=True)
class EvaluationResult:
    safe: bool
    missing_tokens: tuple[str, ...]
    filler_removed: int
    punctuation_added: bool
    paragraph_intent_preserved: bool


def protected_tokens(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in TOKEN_PATTERNS:
        found.extend(match.group(0).rstrip(".,;!?") for match in pattern.finditer(text))
    return tuple(dict.fromkeys(found))


def evaluate_cleanup(source: str, candidate: str) -> EvaluationResult:
    missing = tuple(token for token in protected_tokens(source) if token not in candidate)
    fillers = re.findall(r"\b(?:um+|uh+|you know)\b", source, re.IGNORECASE)
    remaining = re.findall(r"\b(?:um+|uh+|you know)\b", candidate, re.IGNORECASE)
    source_paragraphs = len(re.split(r"\n\s*\n", source.strip()))
    candidate_paragraphs = len(re.split(r"\n\s*\n", candidate.strip()))
    paragraphs_preserved = source_paragraphs <= 1 or candidate_paragraphs >= source_paragraphs
    return EvaluationResult(
        safe=not missing and paragraphs_preserved,
        missing_tokens=missing,
        filler_removed=max(0, len(fillers) - len(remaining)),
        punctuation_added=sum(candidate.count(mark) for mark in ".?!") > sum(source.count(mark) for mark in ".?!"),
        paragraph_intent_preserved=paragraphs_preserved,
    )


def guarded_cleanup(source: str, candidate: str) -> str:
    return candidate if evaluate_cleanup(source, candidate).safe else source
