"""Helpers for grouping tree leaves into readable format sections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from uab.core.models import Asset, StandardAsset


@dataclass
class FormatSection:
    """Synthetic tree section that groups sibling leaves by file format."""

    format_key: str
    name: str
    children: list[Asset | StandardAsset]


def _asset_format(item: Asset | StandardAsset) -> str:
    """Resolve a lowercase file format key for a leaf item."""
    meta = getattr(item, "metadata", None)
    if isinstance(meta, dict):
        fmt_any = meta.get("format")
        if isinstance(fmt_any, str):
            fmt = fmt_any.strip().lower().lstrip(".")
            if fmt:
                return fmt

    local_path = getattr(item, "local_path", None)
    if isinstance(local_path, Path):
        suffix = local_path.suffix.lower().lstrip(".")
        if suffix:
            return suffix

    for text_any in (getattr(item, "name", None), getattr(item, "external_id", None)):
        if isinstance(text_any, str) and text_any:
            suffix = Path(text_any).suffix.lower().lstrip(".")
            if suffix:
                return suffix

    return "unknown"


def _section_label(fmt: str, count: int) -> str:
    ext = fmt.upper() if fmt != "unknown" else "UNKNOWN"
    noun = "file" if count == 1 else "files"
    return f"{ext} {noun} ({count})"


def group_leaf_children_by_format(children: Sequence[Any]) -> list[Any]:
    """
    Group direct leaf children into format sections when multiple formats exist.

    Returns the original children shape when:
    - children include non-leaf nodes (e.g. nested composites), or
    - there is only one detected file format.
    """
    leaf_children: list[Asset | StandardAsset] = []
    for child in children:
        if isinstance(child, (Asset, StandardAsset)):
            leaf_children.append(child)
        else:
            return list(children)

    if len(leaf_children) < 2:
        return list(children)

    format_order: list[str] = []
    by_format: dict[str, list[Asset | StandardAsset]] = {}
    for child in leaf_children:
        fmt = _asset_format(child)
        if fmt not in by_format:
            by_format[fmt] = []
            format_order.append(fmt)
        by_format[fmt].append(child)

    if len(format_order) < 2:
        return list(children)

    return [
        FormatSection(
            format_key=fmt,
            name=_section_label(fmt, len(by_format[fmt])),
            children=by_format[fmt],
        )
        for fmt in format_order
    ]
