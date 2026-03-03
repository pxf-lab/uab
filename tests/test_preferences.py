"""Tests for user preferences persistence and validation."""

from __future__ import annotations

from pathlib import Path

from uab.core.preferences import (
    HdriQuickImportPreferences,
    PreferencesStore,
    UserPreferences,
    parse_user_preferences,
    serialize_user_preferences,
)


def test_preferences_load_defaults_when_missing(tmp_path: Path) -> None:
    store = PreferencesStore(path=tmp_path / "prefs.json")
    prefs = store.load()

    assert prefs.hdri_quick_import.resolution == "2k"
    assert prefs.hdri_quick_import.file_type == "hdr"
    assert prefs.hdri_quick_import.use_exr is False


def test_preferences_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = PreferencesStore(path=tmp_path / "prefs.json")
    original = UserPreferences(
        hdri_quick_import=HdriQuickImportPreferences(
            resolution="4k",
            file_type="exr",
        )
    )

    store.save(original)
    loaded = store.load()

    assert loaded.hdri_quick_import.resolution == "4k"
    assert loaded.hdri_quick_import.file_type == "exr"
    assert loaded.hdri_quick_import.use_exr is True


def test_preferences_invalid_json_falls_back_to_defaults(tmp_path: Path) -> None:
    prefs_path = tmp_path / "prefs.json"
    prefs_path.write_text("{not-json", encoding="utf-8")

    store = PreferencesStore(path=prefs_path)
    loaded = store.load()

    assert loaded.hdri_quick_import.resolution == "2k"
    assert loaded.hdri_quick_import.file_type == "hdr"


def test_parse_user_preferences_supports_backward_compat_keys() -> None:
    payload = {
        "hdri": {
            "lod": "1k",
            "use_exr": True,
        }
    }

    prefs = parse_user_preferences(payload)

    assert prefs.hdri_quick_import.resolution == "1k"
    assert prefs.hdri_quick_import.file_type == "exr"


def test_update_hdri_quick_import_normalizes_inputs(tmp_path: Path) -> None:
    store = PreferencesStore(path=tmp_path / "prefs.json")

    updated = store.update_hdri_quick_import(
        resolution=" 8K ",
        file_type="EXR",
    )

    assert updated.hdri_quick_import.resolution == "8k"
    assert updated.hdri_quick_import.file_type == "exr"


def test_serialize_user_preferences_includes_schema_version() -> None:
    prefs = UserPreferences(
        hdri_quick_import=HdriQuickImportPreferences(
            resolution="1k",
            file_type="hdr",
        )
    )

    payload = serialize_user_preferences(prefs)

    assert payload["schema_version"] == 1
    assert payload["hdri_quick_import"]["resolution"] == "1k"
    assert payload["hdri_quick_import"]["file_type"] == "hdr"
