"""PolyHaven plugin for cloud asset integration.

Provides access to the free PolyHaven asset library including HDRIs,
textures, and models via their public API.

API Documentation: https://github.com/Poly-Haven/Public-API
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.database import AssetDatabase
from uab.core.interfaces import Browsable
from uab.core.models import AssetStatus, AssetType, StandardAsset
from uab.plugins.base import SharedAssetLibraryUtils

logger = logging.getLogger(__name__)

# PolyHaven API endpoints
API_BASE = "https://api.polyhaven.com"
API_ASSETS = f"{API_BASE}/assets"  # ?t=hdris, ?t=textures, ?t=models
API_INFO = f"{API_BASE}/info"  # /{id}
API_FILES = f"{API_BASE}/files"  # /{id}

_TYPE_MAP = {
    "hdris": AssetType.HDRI,
    "textures": AssetType.TEXTURE,
    "models": AssetType.MODEL,
}

_REVERSE_TYPE_MAP = {v: k for k, v in _TYPE_MAP.items()}

AVAILABLE_RESOLUTIONS = ["1k", "2k", "4k", "8k"]
DEFAULT_RESOLUTION = "2k"


class PolyHavenPlugin(SharedAssetLibraryUtils):
    """
    Plugin for browsing and downloading PolyHaven assets.

    PolyHaven provides free, CC0-licensed HDRIs, textures, and 3D models.
    This plugin integrates with their public API to search, browse, and
    download assets.

    Key behaviors:
    - search() fetches from API and reconciles with local database
    - download() fetches files at specified resolution
    - thumbnails are cached locally
    - downloaded assets are tracked in database
    """

    plugin_id = "polyhaven"
    display_name = "PolyHaven"
    description = "Free CC0 HDRIs, textures, and models from PolyHaven"

    def __init__(
        self,
        db: AssetDatabase | None = None,
        library_root: Path | None = None,
        asset_type_filter: AssetType | None = None,
    ) -> None:
        """
        Initialize the PolyHaven plugin.

        Args:
            db: Optional database instance
            library_root: Root directory for downloaded assets
            asset_type_filter: Optional filter to only show one asset type
        """
        super().__init__(db=db, library_root=library_root)
        self._asset_type_filter = asset_type_filter

    async def search(self, query: str) -> list[Browsable]:
        """
        Search PolyHaven assets.

        Fetches the asset list from the API, reconciles with the local
        database to determine which assets are already downloaded, and
        returns a unified list.

        Args:
            query: Search string (filters by name, empty returns all)

        Returns:
            List of browsables (see interfaces.py)
        """
        # Determine which asset types to fetch
        if self._asset_type_filter:
            types_to_fetch = [self._asset_type_filter]
        else:
            types_to_fetch = list(AssetType)

        all_assets: list[StandardAsset] = []

        for asset_type in types_to_fetch:
            api_type = _REVERSE_TYPE_MAP.get(asset_type)
            if not api_type:
                continue

            try:
                assets = await self._fetch_assets_by_type(api_type, query)
                all_assets.extend(assets)
            except Exception as e:
                logger.error(
                    f"Failed to fetch {api_type} from PolyHaven: {e}")
                # Continue with other types even if one fails

        return all_assets

    async def _fetch_assets_by_type(
        self,
        api_type: str,
        query: str,
    ) -> list[StandardAsset]:
        """
        Fetch assets of a specific type from the API.

        Args:
            api_type: API type parameter (hdris, textures, models)
            query: Search filter

        Returns:
            List of StandardAsset objects
        """
        # Fetch asset list from API
        url = f"{API_ASSETS}?t={api_type}"
        data = await self._fetch_json(url)

        if not isinstance(data, dict):
            logger.warning(f"Unexpected response from {url}: {type(data)}")
            return []

        # Extract external IDs and check which are already downloaded
        external_ids = list(data.keys())
        downloaded_ids = self._db.get_already_downloaded_ids_compared_to_external_source(
            source=self.plugin_id,
            external_ids=external_ids,
        )

        assets: list[StandardAsset] = []
        asset_type = _TYPE_MAP[api_type]

        for external_id, info in data.items():
            name = info.get("name", external_id)

            if query and query.lower() not in name.lower():
                continue

            # Check if this asset is already downloaded
            is_local = external_id in downloaded_ids

            if is_local:
                # Get the full asset from database
                db_asset = self._db.get_asset_by_external_id(
                    source=self.plugin_id,
                    external_id=external_id,
                )
                if db_asset:
                    assets.append(db_asset)
                    continue

            # Build asset from API data
            # Thumbnail URL format: https://cdn.polyhaven.com/asset_img/thumbs/{id}.png?height=256
            thumbnail_url = f"https://cdn.polyhaven.com/asset_img/thumbs/{external_id}.png?height=256"

            asset = StandardAsset(
                source=self.plugin_id,
                external_id=external_id,
                name=name,
                type=asset_type,
                status=AssetStatus.LOCAL if is_local else AssetStatus.CLOUD,
                thumbnail_url=thumbnail_url,
                metadata={
                    "categories": info.get("categories", []),
                    "tags": info.get("tags", []),
                    "authors": info.get("authors", {}),
                    "date_published": info.get("date_published"),
                },
            )
            assets.append(asset)

        return assets

    async def download(
        self,
        asset: StandardAsset,
        resolution: str | None = None,
    ) -> StandardAsset:
        """
        Download a PolyHaven asset to local storage.

        Fetches the asset files at the specified resolution, saves them
        to the library directory, and updates the database.

        Args:
            asset: The asset to download
            resolution: Resolution preference (1k, 2k, 4k, 8k). Defaults to 2k.

        Returns:
            Updated StandardAsset with local_path and status=LOCAL

        Raises:
            ValueError: If asset is not from PolyHaven
            RuntimeError: If download fails
        """
        if asset.source != self.plugin_id:
            raise ValueError(f"Asset is not from PolyHaven: {asset.source}")

        resolution = resolution or DEFAULT_RESOLUTION
        logger.info(f"Downloading {asset.name} at {resolution} resolution")

        asset_dir = self.library_root / asset.external_id
        asset_dir.mkdir(parents=True, exist_ok=True)

        try:
            files_url = f"{API_FILES}/{asset.external_id}"
            files_data = await self._fetch_json(files_url)

            downloaded_files = await self._download_asset_files(
                asset=asset,
                files_data=files_data,
                resolution=resolution,
                dest_dir=asset_dir,
            )

            thumbnail_path = await self.download_thumbnail(asset)

            updated_asset = StandardAsset(
                id=asset.id,
                source=asset.source,
                external_id=asset.external_id,
                name=asset.name,
                type=asset.type,
                status=AssetStatus.LOCAL,
                local_path=asset_dir,
                thumbnail_url=asset.thumbnail_url,
                thumbnail_path=thumbnail_path,
                metadata={
                    **asset.metadata,
                    "files": downloaded_files,
                    "resolution": resolution,
                },
            )

            self._db.upsert_asset(updated_asset)
            logger.info(f"Successfully downloaded {asset.name}")

            return updated_asset

        except Exception as e:
            logger.error(f"Failed to download {asset.name}: {e}")
            if asset_dir.exists():
                import shutil
                shutil.rmtree(asset_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to download {asset.name}: {e}") from e

    async def _download_asset_files(
        self,
        asset: StandardAsset,
        files_data: dict[str, Any],
        resolution: str,
        dest_dir: Path,
    ) -> dict[str, str]:
        """
        Download asset files based on type.

        Args:
            asset: The asset being downloaded
            files_data: File data from the API
            resolution: Requested resolution
            dest_dir: Destination directory

        Returns:
            Dict mapping semantic names to filenames
        """
        downloaded_files: dict[str, str] = {}

        if asset.type == AssetType.HDRI:
            downloaded_files = await self._download_hdri_files(
                files_data, resolution, dest_dir
            )
        elif asset.type == AssetType.TEXTURE:
            downloaded_files = await self._download_texture_files(
                files_data, resolution, dest_dir
            )
        elif asset.type == AssetType.MODEL:
            downloaded_files = await self._download_model_files(
                files_data, resolution, dest_dir
            )

        return downloaded_files

    async def _download_hdri_files(
        self,
        files_data: dict[str, Any],
        resolution: str,
        dest_dir: Path,
    ) -> dict[str, str]:
        """Download HDRI files."""
        downloaded: dict[str, str] = {}

        # HDRIs have a simple structure: hdri/{resolution}/{filename}
        hdri_data = files_data.get("hdri", {})
        resolution_data = hdri_data.get(resolution, {})

        if not resolution_data:
            available = list(hdri_data.keys())
            if available:
                resolution = available[0]
                resolution_data = hdri_data[resolution]
                logger.warning(
                    f"Requested resolution not available, using {resolution}")

        for format_name, format_data in resolution_data.items():
            if format_name == "hdr":
                url = format_data.get("url")
                if url:
                    filename = url.split("/")[-1]
                    dest_path = dest_dir / filename
                    await self._download_file(url, dest_path)
                    downloaded["hdri"] = filename
                    break

        return downloaded

    async def _download_texture_files(
        self,
        files_data: dict[str, Any],
        resolution: str,
        dest_dir: Path,
    ) -> dict[str, str]:
        """Download texture map files."""
        downloaded: dict[str, str] = {}

        # Structure: {map_type}/{resolution}/{format}/{url}

        map_types = [
            "diffuse", "diff",
            "normal", "nor_gl", "nor_dx",
            "roughness", "rough",
            "displacement", "disp",
            "arm",  # for anyone unfamiliar, this is ambient occlusion/roughness/metallic packed into a single texture
            "ao",
            "metallic", "metal",
        ]

        for map_type in map_types:
            map_data = files_data.get(map_type, {})
            if not map_data:
                continue

            resolution_data = map_data.get(resolution, {})
            if not resolution_data:
                available = list(map_data.keys())
                if available:
                    resolution_data = map_data[available[0]]

            if not resolution_data:
                continue

            for fmt in ["png", "jpg", "exr"]:
                if fmt in resolution_data:
                    url = resolution_data[fmt].get("url")
                    if url:
                        filename = url.split("/")[-1]
                        dest_path = dest_dir / filename
                        await self._download_file(url, dest_path)
                        downloaded[map_type] = filename
                        break

        return downloaded

    async def _download_model_files(
        self,
        files_data: dict[str, Any],
        resolution: str,
        dest_dir: Path,
    ) -> dict[str, str]:
        """Download 3D model files."""
        downloaded: dict[str, str] = {}

        for fmt in ["gltf", "fbx", "blend"]:
            fmt_data = files_data.get(fmt, {})
            if not fmt_data:
                continue

            resolution_data = fmt_data.get(resolution, {})
            if not resolution_data:
                available = list(fmt_data.keys())
                if available:
                    resolution_data = fmt_data[available[0]]

            if not resolution_data:
                continue

            for file_key, file_data in resolution_data.items():
                url = file_data.get("url")
                if url:
                    filename = url.split("/")[-1]
                    dest_path = dest_dir / filename
                    await self._download_file(url, dest_path)
                    downloaded[f"model_{file_key}"] = filename

            if downloaded:
                break

        return downloaded

    @property
    def can_download(self) -> bool:
        """PolyHaven plugin supports downloading cloud assets."""
        return True

    @property
    def can_remove(self) -> bool:
        """PolyHaven plugin does not directly remove assets.

        Use the LocalLibraryPlugin to remove downloaded assets.
        """
        return False

    def get_settings_schema(self, asset: StandardAsset) -> dict[str, Any] | None:
        """
        Return resolution settings schema for download.

        Args:
            asset: The asset to get settings for

        Returns:
            Settings schema dict with resolution options
        """
        return {
            "resolution": {
                "type": "choice",
                "options": AVAILABLE_RESOLUTIONS,
                "default": DEFAULT_RESOLUTION,
            }
        }

    async def get_asset_info(self, external_id: str) -> dict[str, Any] | None:
        """
        Fetch detailed info for a specific asset.

        Args:
            external_id: The PolyHaven asset ID

        Returns:
            Asset info dict or None if not found
        """
        try:
            url = f"{API_INFO}/{external_id}"
            return await self._fetch_json(url)
        except Exception as e:
            logger.error(f"Failed to fetch asset info for {external_id}: {e}")
            return None
