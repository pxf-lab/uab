"""Persistent user preferences for UAB."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any

from uab.core import config

logger = logging.getLogger(__name__)

PREFERENCES_SCHEMA_VERSION = 1

# TODO: make this configurable
DEFAULT_HDRI_RESOLUTION = "2k"
DEFAULT_HDRI_FILE_TYPE = "hdr"

VALID_HDRI_RESOLUTIONS = ("1k", "2k", "4k", "8k")
VALID_HDRI_FILE_TYPES = ("hdr", "exr")


def _normalize_choice(value: Any, *, valid: tuple[str, ...], default: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in valid:
            return normalized
    return default


def normalize_hdri_resolution(value: Any) -> str:
    """Normalize an HDRI resolution/LOD preference value."""
    return _normalize_choice(
        value,
        valid=VALID_HDRI_RESOLUTIONS,
        default=DEFAULT_HDRI_RESOLUTION,
    )


def normalize_hdri_file_type(value: Any) -> str:
    """Normalize an HDRI file type preference value."""
    return _normalize_choice(
        value,
        valid=VALID_HDRI_FILE_TYPES,
        default=DEFAULT_HDRI_FILE_TYPE,
    )


@dataclass(frozen=True)
class HdriQuickImportPreferences:
    """User defaults for HDRI quick import behavior."""

    resolution: str = DEFAULT_HDRI_RESOLUTION
    file_type: str = DEFAULT_HDRI_FILE_TYPE

    @property
    def use_exr(self) -> bool:
        """Compatibility helper for import options payloads."""
        return self.file_type == "exr"


@dataclass(frozen=True)
class UserPreferences:
    """Top-level UAB user preferences."""

    hdri_quick_import: HdriQuickImportPreferences = field(
        default_factory=HdriQuickImportPreferences
    )


def _parse_hdri_quick_import_section(value: Any) -> HdriQuickImportPreferences:
    if not isinstance(value, dict):
        return HdriQuickImportPreferences()

    resolution_value = value.get("resolution")
    if resolution_value is None:
        # Optional backward-compatible alias.
        resolution_value = value.get("lod")

    file_type_value = value.get("file_type")
    if file_type_value is None and isinstance(value.get("use_exr"), bool):
        file_type_value = "exr" if value.get("use_exr") else "hdr"

    return HdriQuickImportPreferences(
        resolution=normalize_hdri_resolution(resolution_value),
        file_type=normalize_hdri_file_type(file_type_value),
    )


def parse_user_preferences(payload: Any) -> UserPreferences:
    """Build validated preferences from a raw JSON payload."""
    if not isinstance(payload, dict):
        return UserPreferences()

    hdri_section = payload.get("hdri_quick_import")
    if hdri_section is None:
        # Optional backward-compatible key.
        hdri_section = payload.get("hdri")

    return UserPreferences(
        hdri_quick_import=_parse_hdri_quick_import_section(hdri_section),
    )


def serialize_user_preferences(prefs: UserPreferences) -> dict[str, Any]:
    """Serialize preferences to a stable JSON payload."""
    hdri = prefs.hdri_quick_import
    return {
        "schema_version": PREFERENCES_SCHEMA_VERSION,
        "hdri_quick_import": {
            "resolution": hdri.resolution,
            "file_type": hdri.file_type,
        },
    }


class PreferencesStore:
    """File-backed preferences store."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config.get_preferences_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UserPreferences:
        """Load preferences from disk with safe fallback defaults."""
        if not self._path.exists():
            return UserPreferences()

        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Failed reading preferences file %s: %s", self._path, e)
            return UserPreferences()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Invalid preferences JSON in %s: %s", self._path, e)
            return UserPreferences()

        return parse_user_preferences(payload)

    def save(self, prefs: UserPreferences) -> None:
        """Persist preferences atomically to disk."""
        payload = serialize_user_preferences(prefs)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(self._path)

    def update_hdri_quick_import(
        self,
        *,
        resolution: str | None = None,
        file_type: str | None = None,
    ) -> UserPreferences:
        """Update and persist HDRI quick-import defaults."""
        current = self.load()
        current_hdri = current.hdri_quick_import

        next_resolution = (
            current_hdri.resolution
            if resolution is None
            else normalize_hdri_resolution(resolution)
        )
        next_file_type = (
            current_hdri.file_type
            if file_type is None
            else normalize_hdri_file_type(file_type)
        )

        updated = UserPreferences(
            hdri_quick_import=HdriQuickImportPreferences(
                resolution=next_resolution,
                file_type=next_file_type,
            ),
        )
        self.save(updated)
        return updated
