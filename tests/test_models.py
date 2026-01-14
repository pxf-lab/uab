from pathlib import Path
from typing import Callable

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
