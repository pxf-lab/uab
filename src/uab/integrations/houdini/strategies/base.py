"""Base render strategy for Houdini integrations.

Provides common functionality shared by all renderer-specific strategies.
"""

from __future__ import annotations

import logging
import re
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uab.core.interfaces import RenderStrategy
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)

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
        "metallic": ["metallic", "metalness", "metal"],
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

    def _resolution_key(self, asset: Asset) -> int:
        """Sort key for comparing resolution strings like '2k', '4k', '4096'."""
        if not isinstance(asset.metadata, dict):
            return 0
        value = asset.metadata.get("resolution")
        if not isinstance(value, str) or not value:
            return 0

        v = value.strip().lower().replace(" ", "")
        m = re.match(r"^(?P<num>\d+(?:\.\d+)?)k$", v)
        if m:
            return int(float(m.group("num")) * 1000)
        m = re.match(r"^(?P<num>\d+)(?:px|p)?$", v)
        if m:
            return int(m.group("num"))
        return 0

    def _select_local_asset_for_resolution(
        self, composite: CompositeAsset, target_resolution: str | None
    ) -> Asset | None:
        """
        Select the best LOCAL leaf Asset for a composite at a given resolution.

        - Filters children to LOCAL Assets only
        - If target_resolution is provided, prefers an exact match
        - Otherwise falls back to the best available (highest resolution)
        """
        local_assets: list[Asset] = [
            c
            for c in composite.children
            if isinstance(c, Asset) and c.status == AssetStatus.LOCAL and c.local_path
        ]
        if not local_assets:
            return None

        if target_resolution:
            exact = [
                a
                for a in local_assets
                if isinstance(a.metadata, dict)
                and a.metadata.get("resolution") == target_resolution
            ]
            if exact:
                return max(exact, key=self._resolution_key)

        return max(local_assets, key=self._resolution_key)

    def _normalize_texture_keys(self, textures: dict[str, Path]) -> dict[str, Path]:
        """
        Normalize texture role keys to canonical names.

        Common variants:
        - diffuse/base_color/albedo -> diffuse
        - normal/nor_gl/nor_dx -> normal
        - roughness/rough -> roughness
        - metallic/metalness -> metallic
        - ao/ambient_occlusion -> ao
        """
        normalized: dict[str, Path] = {}

        def norm_key(key: str) -> str:
            k = key.strip().lower().replace(" ", "_").replace("-", "_")
            k = re.sub(r"_+", "_", k)
            return k

        mapping = {
            # base color / albedo
            "diffuse": "diffuse",
            "base_color": "diffuse",
            "basecolor": "diffuse",
            "albedo": "diffuse",
            # normal
            "normal": "normal",
            "nor": "normal",
            "nrm": "normal",
            "norm": "normal",
            "normal_gl": "normal",
            "normal_dx": "normal",
            "nor_gl": "normal",
            "nor_dx": "normal",
            # roughness
            "roughness": "roughness",
            "rough": "roughness",
            # metallic
            "metallic": "metallic",
            "metalness": "metallic",
            # ao
            "ao": "ao",
            "ambient_occlusion": "ao",
            # keep additional common names stable
            "displacement": "displacement",
            "disp": "displacement",
            "height": "displacement",
            "opacity": "opacity",
            "alpha": "opacity",
            "emission": "emission",
            "emissive": "emission",
        }

        # apply in sorted order for stability
        for k in sorted(textures.keys()):
            p = textures[k]
            nk = mapping.get(norm_key(k), norm_key(k))
            normalized.setdefault(nk, p)

        return normalized

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

    def create_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """
        Default composite material import.

        Builds a role->Path mapping from TEXTURE children and delegates to
        `create_material_from_textures()`.
        """
        if composite.composite_type != CompositeType.MATERIAL:
            raise ValueError(
                f"Expected MATERIAL composite, got: {composite.composite_type}"
            )

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        textures: dict[str, Path] = {}
        for child in composite.children:
            if not isinstance(child, CompositeAsset):
                continue
            if child.composite_type != CompositeType.TEXTURE:
                continue

            role_any = child.metadata.get("role") if isinstance(child.metadata, dict) else None
            role = role_any if isinstance(role_any, str) and role_any else child.name

            selected = self._select_local_asset_for_resolution(child, target_resolution)
            if selected and selected.local_path:
                textures[role] = selected.local_path

        return self.create_material_from_textures(composite.name, textures, options)

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
