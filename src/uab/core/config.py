"""Centralized configuration for UAB paths and settings.

This module provides consistent paths for caching, storage, and other
application data across all plugins and integrations.
"""

from __future__ import annotations

import platform
from pathlib import Path

APP_BUNDLE_ID = "com.pixelfoundry.uab"


def get_app_support_dir() -> Path:
    """
    Get the application support directory for the current platform.

    Returns:
        Path to the app support directory:
            macOS: ~/Library/Application Support/com.pixelfoundry/uab
            Windows: %APPDATA%/com.pixelfoundry/uab
            Linux: ~/.local/share/com.pixelfoundry/uab
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        import os
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = Path.home() / "AppData" / "Roaming"
    else:  # Linux
        base = Path.home() / ".local" / "share"

    return base / "com.pixelfoundry" / "uab"


def get_cache_dir() -> Path:
    """
    Get the cache directory for temporary/cached data.

    This is used for thumbnails and other cached content that can be
    regenerated if deleted.

    Returns:
        Path to the cache directory
    """
    return get_app_support_dir() / "cache"


def get_thumbnail_cache_dir(plugin_id: str | None = None) -> Path:
    """
    Get the thumbnail cache directory, optionally for a specific plugin.

    Args:
        plugin_id: Optional plugin identifier for plugin-specific cache

    Returns:
        Path to the thumbnail cache directory
    """
    base = get_cache_dir() / "thumbnails"
    if plugin_id:
        return base / plugin_id
    return base


def get_library_dir() -> Path:
    """
    Get the library directory for downloaded assets.

    This is where actual asset files are stored after download.

    Returns:
        Path to the library directory
    """
    return get_app_support_dir() / "library"


def get_database_path() -> Path:
    """
    Get the path to the SQLite database file.

    Returns:
        Path to the database file
    """
    return get_app_support_dir() / "assets.db"


def get_preferences_path() -> Path:
    """
    Get the path to the user preferences JSON file.

    Returns:
        Path to the preferences file
    """
    return get_app_support_dir() / "preferences.json"


def _ensure_directories() -> None:
    """Create all necessary directories if they don't exist."""
    dirs = [
        get_app_support_dir(),
        get_cache_dir(),
        get_thumbnail_cache_dir(),
        get_library_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# On import, ensur all necessary directories exist
_ensure_directories()
