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


@dataclass(frozen=True, slots=True)
class NodeRef:
    """Stable address for a composite node.

    `StandardAsset.id` is not stable across refreshes for cloud search results,
    so composite nodes must be keyed off `(source, external_id, path)`.
    """

    source: str
    external_id: str
    path: tuple[str, ...] = ()


def make_node_id(ref: NodeRef) -> str:
    """Create a deterministic, short-ish node ID for a NodeRef."""

    payload = json.dumps(
        {"source": ref.source, "external_id": ref.external_id, "path": ref.path},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


@dataclass(slots=True)
class AssetNode:
    """A composite projection node.

    Nodes form a tree (optionally populated eagerly). `node_id` is derived from
    `ref` so it's stable across refreshes and safe for UI/presenter selection.
    """

    ref: NodeRef
    label: str
    kind: CompositeNodeKind
    status: CompositeStatus
    metadata: dict[str, Any] = field(default_factory=dict)
    has_children: bool = False
    children: list["AssetNode"] | None = None
    node_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.node_id = make_node_id(self.ref)
        if self.children is not None:
            self.has_children = bool(self.children)
