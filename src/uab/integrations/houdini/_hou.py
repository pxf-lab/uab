"""Helpers for accessing Houdini's `hou` module.

Houdini's Python API (`hou`) only exists inside a Houdini session. This module
centralizes that optional dependency so the rest of the codebase remains
importable in non-Houdini contexts (tests, type-checking, etc.).
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

_HOU: ModuleType | None = None


def _try_load_hou() -> ModuleType | None:
    """Return the `hou` module if importable, else None (cached)."""
    global _HOU
    if _HOU is not None:
        return _HOU

    try:
        _HOU = importlib.import_module("hou")
    except Exception:
        return None

    return _HOU


def has_hou() -> bool:
    """Return True if Houdini's `hou` module can be imported."""
    return _try_load_hou() is not None


def require_hou() -> Any:
    """Return Houdini's `hou` module or raise a helpful error."""
    mod = _try_load_hou()
    if mod is None:
        raise RuntimeError(
            "Houdini Python module 'hou' is not available. "
            "This operation must be run inside a Houdini Python session."
        )
    return mod

