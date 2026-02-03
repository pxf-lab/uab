from pathlib import Path
from typing import Callable

from uab.core.interfaces import Browsable
from uab.core.models import AssetStatus, AssetType, StandardAsset


def test_standard_asset_path_and_enum_conversion(
    make_asset: Callable[..., StandardAsset],
) -> None:
    asset = make_asset(
        source="polyhaven",
        name="Stone",
        type="texture",
        status="cloud",
        local_path="/tmp/stone",
        thumbnail_path="/tmp/stone_thumb.jpg",
    )

    assert isinstance(asset.local_path, Path)
    assert isinstance(asset.thumbnail_path, Path)
    assert asset.type == AssetType.TEXTURE
    assert asset.status == AssetStatus.CLOUD
    assert asset.id.startswith("polyhaven-Stone-")


def test_standard_asset_to_from_dict_roundtrip(make_asset: Callable[..., StandardAsset]) -> None:
    asset = make_asset()
    data = asset.to_dict()
    restored = StandardAsset.from_dict(data)

    assert restored.source == asset.source
    assert restored.external_id == asset.external_id
    assert restored.name == asset.name
    assert restored.type == asset.type
    assert restored.status == asset.status
    assert restored.local_path == asset.local_path
    assert restored.thumbnail_url == asset.thumbnail_url
    assert restored.thumbnail_path == asset.thumbnail_path
    assert restored.metadata == asset.metadata


def test_standard_asset_is_browsable(make_asset: Callable[..., StandardAsset]) -> None:
    asset = make_asset(status=AssetStatus.CLOUD)
    assert isinstance(asset, Browsable)
    assert asset.display_status == asset.status
