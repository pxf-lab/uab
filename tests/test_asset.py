from __future__ import annotations

from pathlib import Path

from uab.core.interfaces import Browsable
from uab.core.models import Asset, AssetStatus, AssetType


def test_asset_instantiation_with_all_fields(tmp_path: Path) -> None:
    local_path = tmp_path / "brick_diffuse_2k.png"
    thumbnail_path = tmp_path / "brick_thumb.jpg"

    asset = Asset(
        id="",
        source="polyhaven",
        external_id="brick_diffuse_2k",
        name="Brick Diffuse 2k",
        asset_type=AssetType.TEXTURE,
        status=AssetStatus.LOCAL,
        local_path=local_path,
        remote_url="https://example.com/brick_diffuse_2k.png",
        thumbnail_url="https://example.com/brick_thumb.jpg",
        thumbnail_path=thumbnail_path,
        file_size=123,
        metadata={"resolution": "2k"},
    )

    assert asset.id.startswith("polyhaven-Brick Diffuse 2k-")
    assert asset.asset_type == AssetType.TEXTURE
    assert asset.status == AssetStatus.LOCAL
    assert asset.local_path == local_path
    assert asset.thumbnail_path == thumbnail_path
    assert asset.display_status == AssetStatus.LOCAL
    assert isinstance(asset, Browsable)


def test_asset_to_from_dict_roundtrip(tmp_path: Path) -> None:
    local_path = tmp_path / "sky_4k.exr"
    thumbnail_path = tmp_path / "sky_thumb.jpg"

    asset = Asset(
        id="asset-1",
        source="polyhaven",
        external_id="sky_4k",
        name="Sky 4k",
        asset_type="hdri",
        status="cloud",
        local_path=str(local_path),
        remote_url="https://example.com/sky_4k.exr",
        thumbnail_url=None,
        thumbnail_path=str(thumbnail_path),
        file_size=456,
        metadata={"resolution": "4k"},
    )

    assert isinstance(asset.local_path, Path)
    assert isinstance(asset.thumbnail_path, Path)
    assert asset.asset_type == AssetType.HDRI
    assert asset.status == AssetStatus.CLOUD

    data = asset.to_dict()
    restored = Asset.from_dict(data)

    assert restored.id == asset.id
    assert restored.source == asset.source
    assert restored.external_id == asset.external_id
    assert restored.name == asset.name
    assert restored.asset_type == asset.asset_type
    assert restored.status == asset.status
    assert restored.local_path == asset.local_path
    assert restored.remote_url == asset.remote_url
    assert restored.thumbnail_url == asset.thumbnail_url
    assert restored.thumbnail_path == asset.thumbnail_path
    assert restored.file_size == asset.file_size
    assert restored.metadata == asset.metadata
    assert restored.display_status == restored.status
    assert isinstance(restored, Browsable)


def test_asset_allows_none_optional_fields() -> None:
    asset = Asset(
        id="asset-2",
        source="local",
        external_id="chair_lod0",
        name="Chair LOD0",
        asset_type=AssetType.MODEL,
        status=AssetStatus.CLOUD,
        local_path=None,
        remote_url=None,
        thumbnail_url=None,
        thumbnail_path=None,
        file_size=None,
        metadata={},
    )

    data = asset.to_dict()
    assert data["local_path"] is None
    assert data["remote_url"] is None
    assert data["thumbnail_url"] is None
    assert data["thumbnail_path"] is None
    assert data["file_size"] is None

    restored = Asset.from_dict(data)
    assert restored.local_path is None
    assert restored.remote_url is None
    assert restored.thumbnail_url is None
    assert restored.thumbnail_path is None
    assert restored.file_size is None


def test_standard_asset_to_asset_conversion(make_asset) -> None:
    std = make_asset(source="polyhaven", name="Stone",
                     type=AssetType.TEXTURE, status=AssetStatus.CLOUD)
    asset = std.to_asset()

    assert isinstance(asset, Asset)
    assert asset.id == std.id
    assert asset.source == std.source
    assert asset.external_id == std.external_id
    assert asset.name == std.name
    assert asset.asset_type == std.type
    assert asset.status == std.status
    assert asset.local_path == std.local_path
    assert asset.thumbnail_path == std.thumbnail_path
    assert asset.metadata == std.metadata
