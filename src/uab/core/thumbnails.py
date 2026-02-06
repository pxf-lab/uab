"""Thumbnail helpers shared across plugins/presenter/UI"""

from __future__ import annotations

from pathlib import Path

from uab.core.models import Asset, AssetType, CompositeAsset


def propagate_preferred_thumbnail(root: CompositeAsset) -> None:
    """
    Propagate an ancestor thumbnail down to descendant Assets.

    Rules:
    - Only applies to descendant `Asset`s of type HDRI or MODEL.
      (textures should preview their actual image files.)
    - Never overwrites an existing `thumbnail_url` / `thumbnail_path` on the Asset.
    - Uses the closest ancestor composite's thumbnail when available.
    """

    def _walk(
        node: CompositeAsset,
        inherited_url: str | None,
        inherited_path: Path | None,
    ) -> None:
        url = node.thumbnail_url or inherited_url
        path = node.thumbnail_path or inherited_path

        for child in node.children:
            if isinstance(child, Asset):
                if child.asset_type in {AssetType.HDRI, AssetType.MODEL}:
                    if not child.thumbnail_url and url:
                        child.thumbnail_url = url
                    if not child.thumbnail_path and path:
                        child.thumbnail_path = path
                continue

            if isinstance(child, CompositeAsset):
                _walk(child, url, path)

    _walk(root, None, None)
