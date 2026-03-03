from pathlib import Path

from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
)
from uab.core.tree_sections import FormatSection, group_leaf_children_by_format


def _make_hdri_asset(
    *,
    asset_id: str,
    name: str,
    fmt: str,
    include_metadata_format: bool = True,
) -> Asset:
    metadata: dict[str, str] = {}
    if include_metadata_format:
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


def test_group_leaf_children_by_format_creates_sections() -> None:
    children = [
        _make_hdri_asset(asset_id="a1", name="sky_8k", fmt="hdr"),
        _make_hdri_asset(asset_id="a2", name="sky_8k", fmt="exr"),
        _make_hdri_asset(asset_id="a3", name="sky_4k", fmt="hdr"),
        _make_hdri_asset(asset_id="a4", name="sky_4k", fmt="exr"),
    ]

    grouped = group_leaf_children_by_format(children)

    assert len(grouped) == 2
    assert all(isinstance(section, FormatSection) for section in grouped)
    hdr_section = grouped[0]
    exr_section = grouped[1]
    assert isinstance(hdr_section, FormatSection)
    assert isinstance(exr_section, FormatSection)
    assert hdr_section.name == "HDR files (2)"
    assert exr_section.name == "EXR files (2)"
    assert [asset.id for asset in hdr_section.children] == ["a1", "a3"]
    assert [asset.id for asset in exr_section.children] == ["a2", "a4"]


def test_group_leaf_children_by_format_uses_path_suffix_when_metadata_missing() -> None:
    children = [
        _make_hdri_asset(
            asset_id="a1",
            name="overcast_8k",
            fmt="hdr",
            include_metadata_format=False,
        ),
        _make_hdri_asset(
            asset_id="a2",
            name="overcast_8k",
            fmt="exr",
            include_metadata_format=False,
        ),
    ]

    grouped = group_leaf_children_by_format(children)

    assert len(grouped) == 2
    assert [section.name for section in grouped] == ["HDR file (1)", "EXR file (1)"]


def test_group_leaf_children_by_format_keeps_original_when_mixed_child_types() -> None:
    leaf = _make_hdri_asset(asset_id="leaf", name="sunny_8k", fmt="hdr")
    nested = CompositeAsset(
        id="nested",
        source="test",
        external_id="nested",
        name="nested",
        composite_type=CompositeType.HDRI,
        children=[],
    )

    children = [leaf, nested]
    grouped = group_leaf_children_by_format(children)

    assert grouped == children


def test_group_leaf_children_by_format_keeps_original_when_single_format() -> None:
    children = [
        _make_hdri_asset(asset_id="a1", name="misty_8k", fmt="hdr"),
        _make_hdri_asset(asset_id="a2", name="misty_4k", fmt="hdr"),
    ]

    grouped = group_leaf_children_by_format(children)

    assert grouped == children
