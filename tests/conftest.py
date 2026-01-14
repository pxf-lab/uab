from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture
def make_asset(tmp_path: Path) -> Callable[..., StandardAsset]:
    from uab.core.models import AssetStatus, AssetType, StandardAsset

    def _make(**overrides):
        # Create a unique directory for this specific asset creation
        # to ensure no collisions between multiple assets in one test.
        asset_dir = tmp_path / overrides.get("external_id", "default_id")
        asset_dir.mkdir(exist_ok=True)

        data = {
            "id": "ignored-id",
            "source": "local",
            "external_id": "brick_01",
            "name": "Brick",
            "type": AssetType.TEXTURE,
            "status": AssetStatus.LOCAL,
            "local_path": asset_dir / "brick",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "thumbnail_path": asset_dir / "thumb.jpg",
            "metadata": {"files": {"diffuse": "brick_diffuse.png"}},
        }
        data.update(overrides)
        return StandardAsset(**data)

    return _make
