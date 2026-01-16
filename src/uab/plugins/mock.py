"""Mock plugin for development and testing.

This plugin provides hardcoded test assets to allow testing the
presenter and UI layers before real plugins are implemented.
"""

from __future__ import annotations

import logging
from pathlib import Path

from uab.core.interfaces import AssetLibraryPlugin
from uab.core.models import StandardAsset, AssetStatus, AssetType

logger = logging.getLogger(__name__)


class MockPlugin(AssetLibraryPlugin):
    """
    Mock asset library plugin for development and testing.

    Provides a small set of hardcoded assets to test the UI and
    presenter layers without requiring real data sources.
    """

    plugin_id = "mock"
    display_name = "Mock Assets (Dev)"
    description = "Mock assets for development and testing"

    def __init__(self) -> None:
        self._assets = self._create_mock_assets()

    def _create_mock_assets(self) -> list[StandardAsset]:
        """Create mock assets for testing."""
        # Try to use real test HDRIs if available
        hdri_dir = Path.home() / "Downloads" / "test_hdris"

        assets = [
            StandardAsset(
                source=self.plugin_id,
                external_id="sunset_beach",
                name="Sunset Beach",
                type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
                local_path=hdri_dir / "sunset_beach_1k.hdr" if hdri_dir.exists() else None,
                thumbnail_url="https://example.com/sunset_beach_thumb.jpg",
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="forest_clearing",
                name="Forest Clearing",
                type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
                local_path=hdri_dir / "forest_clearing_1k.hdr" if hdri_dir.exists() else None,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="studio_softbox",
                name="Studio Softbox",
                type=AssetType.HDRI,
                status=AssetStatus.CLOUD,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="mountain_vista",
                name="Mountain Vista",
                type=AssetType.HDRI,
                status=AssetStatus.CLOUD,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="brick_wall",
                name="Brick Wall",
                type=AssetType.TEXTURE,
                status=AssetStatus.LOCAL,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="wood_planks",
                name="Wood Planks",
                type=AssetType.TEXTURE,
                status=AssetStatus.CLOUD,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="concrete_rough",
                name="Concrete Rough",
                type=AssetType.TEXTURE,
                status=AssetStatus.DOWNLOADING,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="simple_chair",
                name="Simple Chair",
                type=AssetType.MODEL,
                status=AssetStatus.LOCAL,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="office_desk",
                name="Office Desk",
                type=AssetType.MODEL,
                status=AssetStatus.CLOUD,
            ),
        ]

        return assets

    async def search(self, query: str) -> list[StandardAsset]:
        """
        Search mock assets by name.

        Args:
            query: Search string (empty returns all assets)

        Returns:
            List of matching assets
        """
        if not query:
            return self._assets.copy()

        query_lower = query.lower()
        return [
            asset for asset in self._assets
            if query_lower in asset.name.lower()
        ]

    async def download(
        self, asset: StandardAsset, resolution: str | None = None
    ) -> StandardAsset:
        """
        Mock download - just updates status to LOCAL.

        Args:
            asset: The asset to "download"
            resolution: Ignored for mock

        Returns:
            Updated asset with LOCAL status
        """
        logger.info(f"[Mock] Simulating download of: {asset.name}")

        # Find and update the asset in our list
        for i, a in enumerate(self._assets):
            if a.external_id == asset.external_id:
                # Create updated asset
                updated = StandardAsset(
                    source=a.source,
                    external_id=a.external_id,
                    name=a.name,
                    type=a.type,
                    status=AssetStatus.LOCAL,
                    local_path=Path.home() / ".uab" / "mock" /
                    f"{a.external_id}",
                    thumbnail_url=a.thumbnail_url,
                    thumbnail_path=a.thumbnail_path,
                    metadata=a.metadata,
                )
                self._assets[i] = updated
                return updated

        return asset

    @property
    def can_download(self) -> bool:
        """Mock plugin supports downloads."""
        return True

    @property
    def can_remove(self) -> bool:
        """Mock plugin supports removal."""
        return True

    def get_settings_schema(self, asset: StandardAsset) -> dict | None:
        """Return mock settings schema for HDRIs."""
        if asset.type == AssetType.HDRI:
            return {
                "resolution": {
                    "type": "choice",
                    "options": ["1k", "2k", "4k"],
                    "default": "2k",
                }
            }
        return None
