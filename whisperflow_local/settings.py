"""Versioned, validated, atomic user settings layered over bundled defaults."""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .paths import AppPaths

SETTINGS_VERSION = 1


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(
        self, defaults_path: Path, paths: AppPaths | None = None
    ) -> None:
        self.defaults_path = Path(defaults_path)
        self.paths = paths or AppPaths.discover()

    def load(self) -> dict[str, Any]:
        defaults = self._load_defaults()
        if not self.paths.settings.exists():
            self.validate(defaults)
            return defaults
        try:
            raw = json.loads(self.paths.settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsError(f"could not read user settings: {exc}") from exc
        if not isinstance(raw, dict):
            raise SettingsError("user settings must be an object")
        version = raw.pop("schema_version", None)
        if version != SETTINGS_VERSION:
            raise SettingsError(
                f"unsupported settings schema {version!r}; expected {SETTINGS_VERSION}"
            )
        merged = _deep_merge(defaults, raw)
        self.validate(merged)
        return merged

    def save_overrides(self, overrides: dict[str, Any]) -> None:
        if not isinstance(overrides, dict):
            raise SettingsError("settings overrides must be an object")
        defaults = self._load_defaults()
        merged = _deep_merge(defaults, deepcopy(overrides))
        self.validate(merged)
        payload = {"schema_version": SETTINGS_VERSION, **deepcopy(overrides)}
        self.paths.ensure()
        directory = self.paths.settings.parent
        fd, temp_name = tempfile.mkstemp(
            prefix=".settings-", suffix=".json", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.paths.settings)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def _load_defaults(self) -> dict[str, Any]:
        try:
            value = yaml.safe_load(self.defaults_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SettingsError(f"could not read bundled defaults: {exc}") from exc
        if not isinstance(value, dict):
            raise SettingsError("bundled defaults must be an object")
        return value

    @staticmethod
    def validate(value: dict[str, Any]) -> None:
        required = {
            "hotkey", "audio", "stt", "cleanup", "insert", "overlay", "logging"
        }
        missing = required - set(value)
        if missing:
            raise SettingsError(f"missing settings sections: {', '.join(sorted(missing))}")
        _string(value, "hotkey", "combo")
        _integer(value, "audio", "sample_rate", minimum=8000, maximum=96000)
        _integer(value, "audio", "channels", minimum=1, maximum=2)
        _integer(value, "audio", "max_seconds", minimum=1, maximum=3600)
        _string(value, "stt", "model")
        _integer(value, "stt", "batch_size", minimum=1, maximum=128)
        _number(value, "stt", "min_duration_s", minimum=0, maximum=30)
        _number(value, "stt", "min_rms", minimum=0, maximum=1)
        provider = _string(value, "cleanup", "provider")
        if provider not in {"openai-compatible", "omlx", "unsloth-cli", "ollama"}:
            raise SettingsError(f"unsupported cleanup provider: {provider}")
        _string(value, "cleanup", "model")
        _string(value, "cleanup", "prompt")
        _number(value, "cleanup", "max_expansion_ratio", minimum=1, maximum=10)
        mode = _string(value, "insert", "mode")
        if mode not in {"paste", "type"}:
            raise SettingsError(f"unsupported insertion mode: {mode}")
        _number(value, "insert", "settle_delay_s", minimum=0, maximum=10)
        _boolean(value, "insert", "press_enter_after")
        _boolean(value, "overlay", "enabled")
        _boolean(value, "logging", "metadata_only")
        _boolean(value, "logging", "log_transcripts")
        if "performance" in value:
            profile = _string(value, "performance", "profile")
            if profile not in {"instant", "quality"}:
                raise SettingsError(f"unsupported performance profile: {profile}")
            _boolean(value, "performance", "streaming_enabled")
            _boolean(value, "performance", "streaming_gate_passed")
        if "personalization" in value:
            mode = _string(value, "personalization", "writing_mode")
            if mode not in {"natural", "polished", "verbatim", "email"}:
                raise SettingsError(f"unsupported writing mode: {mode}")
            section = _section(value, "personalization")
            if not isinstance(section.get("per_app_modes"), dict):
                raise SettingsError("personalization.per_app_modes must be an object")
            invalid_modes = set(section.get("per_app_modes", {}).values()) - {
                "natural", "polished", "verbatim", "email"
            }
            if invalid_modes:
                raise SettingsError("personalization.per_app_modes contains an unsupported mode")
            if not isinstance(section.get("vocabulary"), list):
                raise SettingsError("personalization.vocabulary must be a list")
            if not isinstance(section.get("replacements"), list):
                raise SettingsError("personalization.replacements must be a list")
        if "history" in value:
            _boolean(value, "history", "enabled")
            _integer(value, "history", "retention_days", minimum=1, maximum=365)
        if "privacy" in value:
            _integer(value, "privacy", "recovery_ttl_seconds", minimum=30, maximum=86400)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overrides.items():
        if key == "schema_version":
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _section(value: dict[str, Any], section: str) -> dict[str, Any]:
    found = value.get(section)
    if not isinstance(found, dict):
        raise SettingsError(f"{section} must be an object")
    return found


def _string(value, section, key) -> str:
    found = _section(value, section).get(key)
    if not isinstance(found, str) or not found.strip():
        raise SettingsError(f"{section}.{key} must be a non-empty string")
    return found


def _number(value, section, key, minimum, maximum) -> float:
    found = _section(value, section).get(key)
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        raise SettingsError(f"{section}.{key} must be a number")
    if not minimum <= found <= maximum:
        raise SettingsError(f"{section}.{key} must be between {minimum} and {maximum}")
    return float(found)


def _integer(value, section, key, minimum, maximum) -> int:
    found = _section(value, section).get(key)
    if isinstance(found, bool) or not isinstance(found, int):
        raise SettingsError(f"{section}.{key} must be an integer")
    if not minimum <= found <= maximum:
        raise SettingsError(f"{section}.{key} must be between {minimum} and {maximum}")
    return found


def _boolean(value, section, key) -> bool:
    found = _section(value, section).get(key)
    if not isinstance(found, bool):
        raise SettingsError(f"{section}.{key} must be true or false")
    return found
