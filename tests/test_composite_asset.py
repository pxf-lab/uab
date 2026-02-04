from __future__ import annotations

from pathlib import Path

from uab.core.interfaces import Browsable
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
)


def _asset(
    *,
    id: str,
    status: AssetStatus,
    role: str | None = None,
) -> Asset:
    meta = {}
    if role is not None:
        meta["role"] = role
    return Asset(
        id=id,
        source="test",
        external_id=id,
        name=id,
        asset_type=AssetType.TEXTURE,
        status=status,
        metadata=meta,
    )


def test_empty_composite_defaults_to_cloud() -> None:
    composite = CompositeAsset(
        id="c1",
        source="test",
        external_id="c1",
        name="Empty",
        composite_type=CompositeType.MATERIAL,
        children=[],
    )

    assert isinstance(composite, Browsable)
    assert composite.display_status == AssetStatus.CLOUD
    assert composite.is_mixed is False


def test_composite_status_all_local_leaves_is_local() -> None:
    composite = CompositeAsset(
        id="c2",
        source="test",
        external_id="c2",
        name="All Local",
        composite_type=CompositeType.TEXTURE,
        children=[
            _asset(id="a1", status=AssetStatus.LOCAL),
            _asset(id="a2", status=AssetStatus.LOCAL),
        ],
    )

    assert composite.display_status == AssetStatus.LOCAL
    assert composite.has_local_children is True
    assert composite.has_cloud_children is False
    assert composite.is_mixed is False
    assert [a.id for a in composite.get_all_assets()] == ["a1", "a2"]


def test_composite_status_all_cloud_leaves_is_cloud() -> None:
    composite = CompositeAsset(
        id="c3",
        source="test",
        external_id="c3",
        name="All Cloud",
        composite_type=CompositeType.TEXTURE,
        children=[
            _asset(id="a1", status=AssetStatus.CLOUD),
            _asset(id="a2", status=AssetStatus.CLOUD),
        ],
    )

    assert composite.display_status == AssetStatus.CLOUD
    assert composite.has_local_children is False
    assert composite.has_cloud_children is True
    assert composite.is_mixed is False


def test_composite_status_mixed_leaves_is_cloud_and_mixed_flag_true() -> None:
    composite = CompositeAsset(
        id="c4",
        source="test",
        external_id="c4",
        name="Mixed",
        composite_type=CompositeType.TEXTURE,
        children=[
            _asset(id="a1", status=AssetStatus.LOCAL),
            _asset(id="a2", status=AssetStatus.CLOUD),
        ],
    )

    assert composite.display_status == AssetStatus.CLOUD
    assert composite.has_local_children is True
    assert composite.has_cloud_children is True
    assert composite.is_mixed is True


def test_composite_status_any_downloading_is_downloading() -> None:
    composite = CompositeAsset(
        id="c5",
        source="test",
        external_id="c5",
        name="Downloading",
        composite_type=CompositeType.TEXTURE,
        children=[
            _asset(id="a1", status=AssetStatus.LOCAL),
            _asset(id="a2", status=AssetStatus.DOWNLOADING),
            _asset(id="a3", status=AssetStatus.CLOUD),
        ],
    )

    assert composite.display_status == AssetStatus.DOWNLOADING


def test_nested_composites_status_and_flattening() -> None:
    leaf1 = CompositeAsset(
        id="leaf1",
        source="test",
        external_id="leaf1",
        name="Leaf 1",
        composite_type=CompositeType.TEXTURE,
        children=[
            _asset(id="a1", status=AssetStatus.LOCAL),
            _asset(id="a2", status=AssetStatus.LOCAL),
        ],
    )
    leaf2 = CompositeAsset(
        id="leaf2",
        source="test",
        external_id="leaf2",
        name="Leaf 2",
        composite_type=CompositeType.TEXTURE,
        children=[_asset(id="a3", status=AssetStatus.LOCAL)],
    )
    parent = CompositeAsset(
        id="parent",
        source="test",
        external_id="parent",
        name="Parent",
        composite_type=CompositeType.MATERIAL,
        children=[leaf1, leaf2],
    )
    root = CompositeAsset(
        id="root",
        source="test",
        external_id="root",
        name="Root",
        composite_type=CompositeType.SCENE,
        children=[parent],
    )

    assert root.display_status == AssetStatus.LOCAL
    assert [a.id for a in root.get_all_assets()] == ["a1", "a2", "a3"]
    assert [a.id for a in root.get_local_assets()] == ["a1", "a2", "a3"]


def test_get_child_by_role_and_get_children_by_type() -> None:
    diffuse = _asset(id="diff", status=AssetStatus.CLOUD, role="diffuse")
    normal = _asset(id="nor", status=AssetStatus.CLOUD, role="normal")
    composite = CompositeAsset(
        id="c6",
        source="test",
        external_id="c6",
        name="Roles",
        composite_type=CompositeType.TEXTURE,
        children=[diffuse, normal],
    )

    assert composite.get_child_by_role("diffuse") is diffuse
    assert composite.get_child_by_role("missing") is None

    children = composite.get_children_by_type(Asset)
    assert [c.id for c in children] == ["diff", "nor"]


def test_composite_to_from_dict_roundtrip(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.png"

    composite = CompositeAsset(
        id="c7",
        source="test",
        external_id="c7",
        name="Roundtrip",
        composite_type=CompositeType.MATERIAL,
        thumbnail_url="https://example.com/thumb.png",
        thumbnail_path=thumb,
        metadata={"hello": "world"},
        children=[
            CompositeAsset(
                id="leaf",
                source="test",
                external_id="leaf",
                name="Leaf",
                composite_type=CompositeType.TEXTURE,
                children=[
                    _asset(id="a1", status=AssetStatus.CLOUD),
                    _asset(id="a2", status=AssetStatus.LOCAL),
                ],
            )
        ],
    )

    data = composite.to_dict()
    restored = CompositeAsset.from_dict(data)

    assert restored.to_dict() == data
    assert restored.display_status == composite.display_status
    assert restored.is_mixed == composite.is_mixed
    assert isinstance(restored, Browsable)
