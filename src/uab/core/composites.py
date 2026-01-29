"""Composite asset projection types.

This module defines runtime-only data structures used to represent "composite"
assets (variants, components, files, references) without changing the persisted
`StandardAsset`.

These are computed when a user selects an asset in the UI.

This system exists because the application was built using the assumption that
StandardAssets would be good enough everywhere, but they don't do a good job
of handling relationships between assets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any


class CompositeNodeKind(str, Enum):
    """Semantic kind for a composite projection node."""

    # Root node representing the asset as a whole (keyed by source/external_id).
    ASSET = "asset"
    # A selectable option under an asset (e.g. resolution, LOD, format, renderer).
    VARIANT = "variant"
    # A semantic grouping under a variant (e.g. "Textures", "Geometry", "Maps").
    COMPONENT = "component"
    # A concrete file leaf (typically one role/key pointing to a relative path).
    FILE = "file"
    # A pointer to another node/asset (used for nesting or cross-links).
    REFERENCE = "reference"


class CompositeStatus(str, Enum):
    """View-level availability status for composite nodes."""

    CLOUD = "cloud"
    LOCAL = "local"
    # A parent node with a mix of LOCAL and CLOUD descendants (partial download).
    MIXED = "mixed"
    # A locally-derived composite missing required roles/files (no cloud truth needed).
    INCOMPLETE = "incomplete"

