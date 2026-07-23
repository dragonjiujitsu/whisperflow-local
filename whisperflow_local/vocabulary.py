from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class VocabularyData:
    terms: tuple[str, ...] = ()
    replacements: tuple[tuple[str, str], ...] = ()

    def apply(self, text: str) -> str:
        result = text
        for source, target in self.replacements:
            result = result.replace(source, target)
        return result


class VocabularyStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> VocabularyData:
        if not self.path.exists():
            return VocabularyData()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        terms = tuple(_clean_term(item) for item in raw.get("terms", []))
        replacements = tuple(
            (_clean_term(pair[0]), _clean_term(pair[1]))
            for pair in raw.get("replacements", [])
        )
        _reject_collisions(replacements)
        return VocabularyData(terms, replacements)

    def save(self, data: VocabularyData) -> None:
        _reject_collisions(data.replacements)
        _atomic_private_json(self.path, {
            "schema_version": 1,
            "terms": list(data.terms),
            "replacements": [list(pair) for pair in data.replacements],
        })

    def export_to(self, destination: Path) -> None:
        destination.write_text(json.dumps(asdict(self.load()), indent=2) + "\n", encoding="utf-8")

    def import_from(self, source: Path) -> VocabularyData:
        raw = json.loads(source.read_text(encoding="utf-8"))
        data = VocabularyData(
            tuple(raw.get("terms", ())),
            tuple(tuple(pair) for pair in raw.get("replacements", ())),
        )
        self.save(data)
        return data

    def delete_all(self) -> None:
        self.path.unlink(missing_ok=True)


def _clean_term(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ValueError("vocabulary entries must be non-empty single-line strings")
    return value.strip()


def _reject_collisions(replacements: tuple[tuple[str, str], ...]) -> None:
    keys = [source.casefold() for source, _ in replacements]
    if len(keys) != len(set(keys)):
        raise ValueError("replacement sources must be unique ignoring case")


def _atomic_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
