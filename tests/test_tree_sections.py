from pathlib import Path

from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
)
from uab.core.tree_sections import (
    ResolutionSection,
    group_leaf_children_by_resolution,
)


def _make_hdri_asset(
    *,
    asset_id: str,
    name: str,
    fmt: str,
    resolution: str,
    include_metadata_resolution: bool = True,
) -> Asset:
    metadata: dict[str, str] = {}
    if include_metadata_resolution:
        metadata["resolution"] = resolution
    metadata["format"] = fmt

    return Asset(
        id=asset_id,
        source="test",
        external_id=asset_id,
        name=name,
        asset_type=AssetType.HDRI,
        status=AssetStatus.LOCAL,
        local_path=Path(f"/tmp/{name}.{fmt}"),
        metadata=metadata,
    )


def test_group_leaf_children_by_resolution_creates_sections() -> None:
    children = [
        _make_hdri_asset(asset_id="a1", name="sky_8k", fmt="hdr", resolution="8k"),
        _make_hdri_asset(asset_id="a2", name="sky_8k", fmt="exr", resolution="8k"),
        _make_hdri_asset(asset_id="a3", name="sky_4k", fmt="hdr", resolution="4k"),
        _make_hdri_asset(asset_id="a4", name="sky_4k", fmt="exr", resolution="4k"),
    ]

    grouped = group_leaf_children_by_resolution(children)

    assert len(grouped) == 2
    assert all(isinstance(section, ResolutionSection) for section in grouped)
    eight_k_section = grouped[0]
    four_k_section = grouped[1]
    assert isinstance(eight_k_section, ResolutionSection)
    assert isinstance(four_k_section, ResolutionSection)
    assert eight_k_section.name == "8K files (2)"
    assert four_k_section.name == "4K files (2)"
    assert [asset.id for asset in eight_k_section.children] == ["a1", "a2"]
    assert [asset.id for asset in four_k_section.children] == ["a3", "a4"]


def test_group_leaf_children_by_resolution_uses_name_suffix_when_metadata_missing() -> None:
    children = [
        _make_hdri_asset(
            asset_id="a1",
            name="overcast_8k",
            fmt="hdr",
            resolution="8k",
            include_metadata_resolution=False,
        ),
        _make_hdri_asset(
            asset_id="a2",
            name="overcast_4k",
            fmt="hdr",
            resolution="4k",
            include_metadata_resolution=False,
        ),
    ]

    grouped = group_leaf_children_by_resolution(children)

    assert len(grouped) == 2
    assert [section.name for section in grouped] == ["8K file (1)", "4K file (1)"]


def test_group_leaf_children_by_resolution_keeps_original_when_mixed_child_types() -> None:
    leaf = _make_hdri_asset(asset_id="leaf", name="sunny_8k", fmt="hdr", resolution="8k")
    nested = CompositeAsset(
        id="nested",
        source="test",
        external_id="nested",
        name="nested",
        composite_type=CompositeType.HDRI,
        children=[],
    )

    children = [leaf, nested]
    grouped = group_leaf_children_by_resolution(children)

    assert grouped == children


def test_group_leaf_children_by_resolution_keeps_original_when_single_resolution() -> None:
    children = [
        _make_hdri_asset(asset_id="a1", name="misty_8k", fmt="hdr", resolution="8k"),
        _make_hdri_asset(asset_id="a2", name="misty_8k", fmt="exr", resolution="8k"),
    ]

    grouped = group_leaf_children_by_resolution(children)

    assert grouped == children
