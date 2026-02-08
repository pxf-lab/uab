"""Helpers for accessing Maya's Python modules.

Autodesk Maya's Python packages (e.g. `maya.cmds`) only exist inside a Maya
session. This module centralizes that optional dependency so the rest of the
codebase remains importable in non-Maya contexts (tests, type-checking, etc.).
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

_CMDS: ModuleType | None = None


def _try_load_cmds() -> ModuleType | None:
    """Return `maya.cmds` if importable, else None (cached)."""
    global _CMDS
    if _CMDS is not None:
        return _CMDS

    try:
        _CMDS = importlib.import_module("maya.cmds")
    except Exception:
        return None

    return _CMDS


def has_cmds() -> bool:
    """Return True if `maya.cmds` can be imported."""
    return _try_load_cmds() is not None


def require_cmds() -> Any:
    """Return `maya.cmds` or raise a helpful error."""
    mod = _try_load_cmds()
    if mod is None:
        raise RuntimeError(
            "Maya Python module 'maya.cmds' is not available. "
            "This operation must be run inside a Maya Python session."
        )
    return mod

