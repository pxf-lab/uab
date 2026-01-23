"""Base render strategy for Houdini integrations.

Provides common functionality shared by all renderer-specific strategies.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uab.core.interfaces import RenderStrategy
from uab.core.models import StandardAsset, AssetType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SharedHoudiniRenderStrategyUtils(RenderStrategy):
    """
    Base class for Houdini renderer strategies.

    Provides common functionality for texture path resolution,
    node naming, and standard PBR texture map handling.

    Subclasses implement renderer-specific node creation.
    """

    # Standard PBR texture map names used in metadata["files"]
    # Maps semantic name -> list of common filename patterns
    TEXTURE_MAP_ALIASES = {
        "diffuse": ["diffuse", "diff", "albedo", "base_color", "basecolor", "color", "col"],
        "roughness": ["roughness", "rough", "glossiness", "gloss"],
        "normal": ["normal", "nor", "nrm", "norm", "normal_gl", "normal_dx"],
        "displacement": ["displacement", "disp", "height", "bump"],
        "metalness": ["metalness", "metal", "metallic"],
        "ao": ["ao", "ambient_occlusion", "occlusion"],
        "opacity": ["opacity", "alpha", "transparency"],
        "emission": ["emission", "emissive", "glow"],
    }

    @property
    @abstractmethod
    def renderer_name(self) -> str:
        """Return the renderer identifier (e.g., 'arnold', 'redshift')."""
        ...

    def _get_texture_path(self, asset: StandardAsset, map_name: str) -> str | None:
        """
        Get the full path to a texture map file.

        Looks up the map in asset.metadata["files"] and combines with
        asset.local_path to get the full path.

        Args:
            asset: The asset containing the texture
            map_name: Semantic map name (e.g., "diffuse", "normal")

        Returns:
            Full path string if found, None otherwise
        """
        if not asset.local_path:
            logger.warning(f"Asset {asset.name} has no local_path")
            return None

        files = asset.metadata.get("files", {})

        if map_name in files:
            return str(asset.local_path / files[map_name])

        aliases = self.TEXTURE_MAP_ALIASES.get(map_name, [])
        for alias in aliases:
            if alias in files:
                return str(asset.local_path / files[alias])

        return None

    def _get_hdri_path(self, asset: StandardAsset) -> str | None:
        """
        Get the path to an HDRI file.

        For HDRI assets, the file is either in metadata["files"]["hdri"]
        or the local_path points directly to the file.

        Args:
            asset: The HDRI asset

        Returns:
            Full path string if found, None otherwise
        """
        if asset.type != AssetType.HDRI:
            logger.warning(f"Asset {asset.name} is not an HDRI")
            return None

        if not asset.local_path:
            logger.warning(f"Asset {asset.name} has no local_path")
            return None

        if asset.local_path.is_file():
            return str(asset.local_path)

        files = asset.metadata.get("files", {})
        if "hdri" in files:
            return str(asset.local_path / files["hdri"])

        hdri_extensions = [".hdr", ".exr", ".hdri"]
        if asset.local_path.is_dir():
            for ext in hdri_extensions:
                for f in asset.local_path.iterdir():
                    if f.suffix.lower() == ext:
                        return str(f)

        return None

    def _sanitize_node_name(self, name: str) -> str:
        """
        Sanitize a string for use as a Houdini node name.

        Replaces invalid characters with underscores.

        Args:
            name: The raw name string

        Returns:
            Sanitized node name
        """
        sanitized = name.replace(" ", "_").replace("-", "_")
        sanitized = "".join(c if c.isalnum() or c ==
                            "_" else "_" for c in sanitized)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        return sanitized

    def _get_material_name(self, asset: StandardAsset) -> str:
        """
        Generate a material node name for the asset.

        Args:
            asset: The asset

        Returns:
            Material node name (e.g., "brick_wall_arnold")
        """
        base_name = self._sanitize_node_name(asset.name)
        return f"{base_name}_{self.renderer_name}"

    def _get_available_maps(self, asset: StandardAsset) -> dict[str, str]:
        """
        Get all available texture maps for an asset.

        Args:
            asset: The asset to check

        Returns:
            Dict of map_name -> full_path for all found maps
        """
        available = {}
        for map_name in self.TEXTURE_MAP_ALIASES.keys():
            path = self._get_texture_path(asset, map_name)
            if path and Path(path).exists():
                available[map_name] = path
        return available

    def _log_import(self, asset: StandardAsset, operation: str) -> None:
        """Log an import operation for debugging."""
        logger.info(
            f"[{self.renderer_name.upper()}] {operation}: {asset.name} "
            f"(type={asset.type.value})"
        )
