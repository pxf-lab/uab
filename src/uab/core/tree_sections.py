"""Helpers for grouping tree leaves into readable resolution sections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Sequence

from uab.core.models import Asset, StandardAsset

_RESOLUTION_RE = re.compile(r"(?:^|[_\-:\s])(?P<resolution>\d+[kK])$")


@dataclass
class ResolutionSection:
    """Synthetic tree section that groups sibling leaves by resolution."""

    resolution_key: str
    name: str
    children: list[Asset | StandardAsset]


def _extract_resolution_from_text(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    stem = Path(text).stem
    match = _RESOLUTION_RE.search(stem)
    if not match:
        return None
    return match.group("resolution").lower()


def _asset_resolution(item: Asset | StandardAsset) -> str:
    """Resolve a lowercase resolution key for a leaf item."""
    meta = getattr(item, "metadata", None)
    if isinstance(meta, dict):
        res_any = meta.get("resolution") or meta.get("lod")
        if isinstance(res_any, str):
            resolution = res_any.strip().lower()
            if resolution:
                return resolution

    local_path = getattr(item, "local_path", None)
    if isinstance(local_path, Path):
        parsed = _extract_resolution_from_text(local_path.stem)
        if parsed:
            return parsed

    for text_any in (getattr(item, "name", None), getattr(item, "external_id", None)):
        if isinstance(text_any, str) and text_any:
            parsed = _extract_resolution_from_text(text_any)
            if parsed:
                return parsed

    return "unknown"


def _section_label(resolution: str, count: int) -> str:
    if resolution == "unknown":
        return f"Unknown resolution ({count})"
    ext = resolution.upper()
    noun = "file" if count == 1 else "files"
    return f"{ext} {noun} ({count})"


def group_leaf_children_by_resolution(children: Sequence[Any]) -> list[Any]:
    """
    Group direct leaf children into resolution sections when multiple resolutions exist.

    Returns the original children shape when:
    - children include non-leaf nodes (e.g. nested composites), or
    - there is only one detected resolution.
    """
    leaf_children: list[Asset | StandardAsset] = []
    for child in children:
        if isinstance(child, (Asset, StandardAsset)):
            leaf_children.append(child)
        else:
            return list(children)

    if len(leaf_children) < 2:
        return list(children)

    resolution_order: list[str] = []
    by_resolution: dict[str, list[Asset | StandardAsset]] = {}
    for child in leaf_children:
        resolution = _asset_resolution(child)
        if resolution not in by_resolution:
            by_resolution[resolution] = []
            resolution_order.append(resolution)
        by_resolution[resolution].append(child)

    if len(resolution_order) < 2:
        return list(children)

    return [
        ResolutionSection(
            resolution_key=resolution,
            name=_section_label(resolution, len(by_resolution[resolution])),
            children=by_resolution[resolution],
        )
        for resolution in resolution_order
    ]


# Backward compatibility for older imports.
FormatSection = ResolutionSection


def group_leaf_children_by_format(children: Sequence[Any]) -> list[Any]:
    """Backward-compatible wrapper for resolution grouping."""
    return group_leaf_children_by_resolution(children)
