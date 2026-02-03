"""Local library plugin for managing downloaded assets.

This plugin provides access to assets that have been downloaded to the
local library, regardless of their original source. It queries the
database directly and supports searching and removal.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from uab.core.database import AssetDatabase
from uab.core.interfaces import Browsable
from uab.core.models import AssetStatus, AssetType, StandardAsset
from uab.plugins.base import SharedAssetLibraryUtils

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class LocalLibraryPlugin(SharedAssetLibraryUtils):
    """
    Plugin for browsing and managing locally downloaded assets.

    This plugin shows all assets that have been downloaded to the local
    library, regardless of their original source (Poly Haven, etc.).

    Key behaviors:
        - search() queries the database for LOCAL status assets
        - can_download is False (assets are already local)
        - can_remove is True (allows deletion of local assets)
        - download() raises NotImplementedError
    """

    plugin_id = "local"
    display_name = "Local Library"
    description = "Browse and manage locally downloaded assets"

    def __init__(
        self,
        db: AssetDatabase | None = None,
        library_root: Path | None = None,
    ) -> None:
        """
        Initialize the local library plugin.

        Args:
            db: Optional database instance
            library_root: Root directory for the local library
        """
        super().__init__(db=db, library_root=library_root)

    async def search(self, query: str) -> list[Browsable]:
        """
        Search local assets by name.

        Queries the database for all assets with LOCAL status,
        optionally filtered by the search query.

        Args:
            query: Search string (empty returns all local assets)

        Returns:
            List of matching local Browsable items (ref interfaces.py)
        """
        if not query:
            # Return all local assets
            return self._db.get_local_assets()

        # Search with name filter
        return self._db.search_assets(query=query, status=AssetStatus.LOCAL)

    async def download(
        self,
        asset: StandardAsset,
        resolution: str | None = None,
    ) -> StandardAsset:
        """
        Not supported - local assets are already downloaded.

        Args:
            asset: The asset (ignored)
            resolution: Resolution preference (ignored)

        Raises:
            NotImplementedError: Always raised as local assets don't need downloading
        """
        raise NotImplementedError(
            "Local library plugin does not support downloading. "
            "Assets are already local."
        )

    @property
    def can_download(self) -> bool:
        """Local plugin does not support downloads (assets are already local)."""
        return False

    @property
    def can_remove(self) -> bool:
        """Local plugin supports removing assets from the library."""
        return True

    def remove_asset(self, asset: StandardAsset) -> bool:
        """
        Remove an asset from the local library.

        This deletes the asset files from disk and removes the
        database record.

        Args:
            asset: The asset to remove

        Returns:
            True if the asset was successfully removed
        """
        logger.info(f"Removing asset from local library: {asset.name}")

        # Delete local files if they exist
        if asset.local_path and asset.local_path.exists():
            try:
                if asset.local_path.is_dir():
                    shutil.rmtree(asset.local_path)
                    logger.debug(f"Deleted directory: {asset.local_path}")
                else:
                    asset.local_path.unlink()
                    logger.debug(f"Deleted file: {asset.local_path}")
            except OSError as e:
                logger.error(f"Failed to delete asset files: {e}")
                # Continue to remove DB record even if file deletion fails

        # Delete thumbnail if it exists
        if asset.thumbnail_path and asset.thumbnail_path.exists():
            try:
                asset.thumbnail_path.unlink()
                logger.debug(f"Deleted thumbnail: {asset.thumbnail_path}")
            except OSError as e:
                logger.warning(f"Failed to delete thumbnail: {e}")

        # Remove from database
        # TODO: should it remove from db even if the files are not deleted?
        deleted = self._db.remove_asset_by_id(asset.id)
        if deleted:
            logger.info(f"Removed asset {asset.name} from database")
        else:
            logger.warning(f"Asset {asset.name} was not found in database")

        return deleted

    def get_settings_schema(self, asset: StandardAsset) -> dict | None:
        """
        Local assets don't need import settings.

        Returns:
            None (no settings dialog needed)
        """
        return None

    _EXTENSION_MAP: dict[str, AssetType] = {
        # HDRI formats
        ".hdr": AssetType.HDRI,
        ".exr": AssetType.HDRI,
        # Texture formats
        ".png": AssetType.TEXTURE,
        ".jpg": AssetType.TEXTURE,
        ".jpeg": AssetType.TEXTURE,
        ".tif": AssetType.TEXTURE,
        ".tiff": AssetType.TEXTURE,
        # Model formats
        ".obj": AssetType.MODEL,
        ".fbx": AssetType.MODEL,
        ".gltf": AssetType.MODEL,
        ".glb": AssetType.MODEL,
        ".usd": AssetType.MODEL,
        ".usda": AssetType.MODEL,
        ".usdc": AssetType.MODEL,
    }

    def add_assets(self, paths: Path | list[Path]) -> list[StandardAsset]:
        """
        Add assets from files or directories.

        Accepts either a single path or list of paths. Each path can be:
        - A file: Added directly if it has a supported extension
        - A directory: Scanned recursively for supported files

        Skips files that already exist in the database.

        Args:
            paths: Single path or list of paths (files or directories)

        Returns:
            List of StandardAsset objects that were added
        """
        # Normalize to list
        if isinstance(paths, Path):
            paths = [paths]

        added_assets: list[StandardAsset] = []
        skipped_count = 0
        unsupported_count = 0

        # Collect all files to process
        files_to_process: list[Path] = []

        for path in paths:
            if not path.exists():
                logger.warning(f"Path does not exist: {path}")
                continue

            if path.is_file():
                files_to_process.append(path)
            elif path.is_dir():
                # scan directory recursively
                for file_path in path.rglob("*"):
                    if file_path.is_file():
                        files_to_process.append(file_path)

        supported_extensions = set(self._EXTENSION_MAP.keys())

        for file_path in files_to_process:
            suffix = file_path.suffix.lower()
            if suffix not in supported_extensions:
                unsupported_count += 1
                logger.debug(f"Skipping unsupported file: {file_path.name}")
                continue

            # Use absolute path as external_id for uniqueness
            external_id = str(file_path.resolve())

            # Check if asset already exists in database
            existing = self._db.get_asset_by_external_id(
                source=self.plugin_id,
                external_id=external_id,
            )
            if existing:
                skipped_count += 1
                logger.debug(f"Skipping existing asset: {file_path.name}")
                continue

            # Determine asset type from extension
            asset_type = self._EXTENSION_MAP[suffix]

            # Create the asset
            asset = StandardAsset(
                source=self.plugin_id,
                external_id=external_id,
                name=file_path.stem,
                type=asset_type,
                status=AssetStatus.LOCAL,
                local_path=file_path,
            )

            self._db.upsert_asset(asset)
            added_assets.append(asset)
            logger.debug(f"Added asset: {asset.name} ({asset_type.value})")

        logger.info(
            f"Added {len(added_assets)} assets "
            f"(skipped {skipped_count} existing, {unsupported_count} unsupported)"
        )

        return added_assets
