"""Tests for thumbnail propagation helpers."""

from __future__ import annotations

from pathlib import Path

from uab.core.models import Asset, AssetStatus, AssetType, CompositeAsset, CompositeType
from uab.core.thumbnails import propagate_preferred_thumbnail


def test_propagate_preferred_thumbnail_sets_hdri_and_model_leaf_thumbnails() -> None:
    thumb_path = Path("/tmp/thumb.png")

    root = CompositeAsset(
        id="root",
        source="polyhaven",
        external_id="sunset_hdri",
        name="Sunset HDRI",
        composite_type=CompositeType.HDRI,
        thumbnail_url="https://example.com/thumb.png",
        thumbnail_path=thumb_path,
        metadata={},
        children=[
            Asset(
                id="hdri-leaf",
                source="polyhaven",
                external_id="sunset_hdri:2k:hdr",
                name="sunset_2k.hdr",
                asset_type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
                local_path=Path("/tmp/sunset_2k.hdr"),
                remote_url=None,
                thumbnail_url=None,
                thumbnail_path=None,
                metadata={},
            ),
            Asset(
                id="model-leaf",
                source="polyhaven",
                external_id="simple_chair:fbx:2k",
                name="chair_2k.fbx",
                asset_type=AssetType.MODEL,
                status=AssetStatus.LOCAL,
                local_path=Path("/tmp/chair_2k.fbx"),
                remote_url=None,
                thumbnail_url=None,
                thumbnail_path=None,
                metadata={},
            ),
            # Textures should not inherit a generic composite thumbnail.
            Asset(
                id="tex-leaf",
                source="polyhaven",
                external_id="rusty_metal:diffuse:2k",
                name="diffuse_2k.png",
                asset_type=AssetType.TEXTURE,
                status=AssetStatus.LOCAL,
                local_path=Path("/tmp/diffuse_2k.png"),
                remote_url=None,
                thumbnail_url=None,
                thumbnail_path=None,
                metadata={},
            ),
        ],
    )

    propagate_preferred_thumbnail(root)

    hdri = root.children[0]
    assert isinstance(hdri, Asset)
    assert hdri.thumbnail_url == "https://example.com/thumb.png"
    assert hdri.thumbnail_path == thumb_path

    model = root.children[1]
    assert isinstance(model, Asset)
    assert model.thumbnail_url == "https://example.com/thumb.png"
    assert model.thumbnail_path == thumb_path

    tex = root.children[2]
    assert isinstance(tex, Asset)
    assert tex.thumbnail_url is None
    assert tex.thumbnail_path is None


def test_propagate_preferred_thumbnail_does_not_override_existing_leaf_thumbnail() -> None:
    root = CompositeAsset(
        id="root",
        source="polyhaven",
        external_id="sunset_hdri",
        name="Sunset HDRI",
        composite_type=CompositeType.HDRI,
        thumbnail_url="https://example.com/root.png",
        thumbnail_path=Path("/tmp/root.png"),
        metadata={},
        children=[
            Asset(
                id="hdri-leaf",
                source="polyhaven",
                external_id="sunset_hdri:2k:hdr",
                name="sunset_2k.hdr",
                asset_type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
                local_path=Path("/tmp/sunset_2k.hdr"),
                remote_url=None,
                thumbnail_url="https://example.com/leaf.png",
                thumbnail_path=Path("/tmp/leaf.png"),
                metadata={},
            ),
        ],
    )

    propagate_preferred_thumbnail(root)

    leaf = root.children[0]
    assert isinstance(leaf, Asset)
    assert leaf.thumbnail_url == "https://example.com/leaf.png"
    assert leaf.thumbnail_path == Path("/tmp/leaf.png")

