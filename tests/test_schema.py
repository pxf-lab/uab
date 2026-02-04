"""Tests for composite schemas (Milestone 9.3)."""

from __future__ import annotations

from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
)
from uab.core.schemas import COMPOSITE_SCHEMAS, get_schema


def test_composite_schemas_cover_all_composite_types() -> None:
    assert set(COMPOSITE_SCHEMAS.keys()) == set(CompositeType)


def test_is_leaf_composite_for_leaf_and_nested_types() -> None:
    leaf = {CompositeType.TEXTURE, CompositeType.MODEL, CompositeType.HDRI}
    nested = set(CompositeType) - leaf

    for t in leaf:
        assert get_schema(t).is_leaf_composite is True

    for t in nested:
        assert get_schema(t).is_leaf_composite is False


def test_is_complete_and_missing_roles_for_required_role_types() -> None:
    hdri_set = CompositeAsset(
        id="hs",
        source="test",
        external_id="hs",
        name="HDRI Set",
        composite_type=CompositeType.HDRI_SET,
        children=[],
    )

    assert hdri_set.is_complete() is False
    assert hdri_set.get_missing_roles() == {"hdri"}
    assert any("Missing required roles" in w for w in hdri_set.validate())

    hdri_child = CompositeAsset(
        id="h",
        source="test",
        external_id="h",
        name="HDRI",
        composite_type=CompositeType.HDRI,
        metadata={"role": "hdri"},
        children=[
            Asset(
                id="a",
                source="test",
                external_id="a",
                name="sunset_2k.hdr",
                asset_type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
                metadata={"resolution": "2k"},
            )
        ],
    )
    hdri_set.children = [hdri_child]

    assert hdri_set.is_complete() is True
    assert hdri_set.get_missing_roles() == set()
    assert not any("Missing required roles" in w for w in hdri_set.validate())


def test_validate_unknown_role_warning() -> None:
    material = CompositeAsset(
        id="m",
        source="test",
        external_id="m",
        name="Mat",
        composite_type=CompositeType.MATERIAL,
        children=[
            CompositeAsset(
                id="t",
                source="test",
                external_id="t",
                name="weird",
                composite_type=CompositeType.TEXTURE,
                metadata={"role": "weird"},
                children=[],
            )
        ],
    )

    warnings = material.validate()
    assert any("Unknown role 'weird' for material" in w for w in warnings)


def test_validate_child_type_not_allowed_warning() -> None:
    material = CompositeAsset(
        id="m",
        source="test",
        external_id="m",
        name="Mat",
        composite_type=CompositeType.MATERIAL,
        children=[
            Asset(
                id="a",
                source="test",
                external_id="a",
                name="diff.png",
                asset_type=AssetType.TEXTURE,
                status=AssetStatus.CLOUD,
                metadata={"role": "diffuse"},
            )
        ],
    )

    warnings = material.validate()
    assert any("Child type Asset not allowed in material" in w for w in warnings)


def test_validate_asset_type_mismatch_warning() -> None:
    texture = CompositeAsset(
        id="t",
        source="test",
        external_id="t",
        name="diffuse",
        composite_type=CompositeType.TEXTURE,
        children=[
            Asset(
                id="a",
                source="test",
                external_id="a",
                name="chair.fbx",
                asset_type=AssetType.MODEL,
                status=AssetStatus.LOCAL,
                metadata={"resolution": "2k"},
            )
        ],
    )

    warnings = texture.validate()
    assert any("expected texture" in w for w in warnings)


def test_validate_expected_child_composite_type_mismatch_warning() -> None:
    material = CompositeAsset(
        id="m",
        source="test",
        external_id="m",
        name="Mat",
        composite_type=CompositeType.MATERIAL,
        children=[
            CompositeAsset(
                id="c",
                source="test",
                external_id="c",
                name="ModelChild",
                composite_type=CompositeType.MODEL,
                metadata={"role": "diffuse"},
                children=[],
            )
        ],
    )

    warnings = material.validate()
    assert any("expected one of" in w for w in warnings)

