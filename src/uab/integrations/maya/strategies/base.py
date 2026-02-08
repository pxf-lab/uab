"""Base render strategy utilities for Maya integrations."""

from __future__ import annotations

import logging
import re
from abc import abstractmethod
from pathlib import Path
from typing import Any

from uab.core.interfaces import RenderStrategy
from uab.core.models import Asset, AssetStatus, CompositeAsset, CompositeType

logger = logging.getLogger(__name__)


class SharedMayaRenderStrategyUtils(RenderStrategy):
    """Base class for Maya renderer strategies with shared helpers."""

    # Standard PBR role variants -> canonical roles
    _ROLE_MAPPING = {
        # base color / albedo
        "diffuse": "diffuse",
        "base_color": "diffuse",
        "basecolor": "diffuse",
        "albedo": "diffuse",
        "color": "diffuse",
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
        "gloss": "roughness",
        "glossiness": "roughness",
        # metallic
        "metallic": "metallic",
        "metalness": "metallic",
        # ao
        "ao": "ao",
        "ambient_occlusion": "ao",
        "occlusion": "ao",
        # displacement
        "displacement": "displacement",
        "disp": "displacement",
        "height": "displacement",
        "bump": "displacement",
        # opacity
        "opacity": "opacity",
        "alpha": "opacity",
        "transparency": "opacity",
        # emission
        "emission": "emission",
        "emissive": "emission",
        "glow": "emission",
    }

    _NON_COLOR_ROLES = {
        "roughness",
        "metallic",
        "normal",
        "ao",
        "displacement",
        "opacity",
    }

    @property
    @abstractmethod
    def renderer_name(self) -> str:
        """Return the renderer identifier (e.g. 'arnold')."""
        raise NotImplementedError

    def _maya_cmds(self):
        import maya.cmds as cmds  # type: ignore

        return cmds

    def _resolution_key(self, asset: Asset) -> int:
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
                if isinstance(a.metadata, dict) and a.metadata.get("resolution") == target_resolution
            ]
            if exact:
                return max(exact, key=self._resolution_key)

        return max(local_assets, key=self._resolution_key)

    def _normalize_texture_keys(self, textures: dict[str, Path]) -> dict[str, Path]:
        """Normalize texture role keys to canonical names used by strategies."""

        def norm_key(key: str) -> str:
            k = key.strip().lower().replace(" ", "_").replace("-", "_")
            k = re.sub(r"_+", "_", k)
            return k

        normalized: dict[str, Path] = {}
        for k in sorted(textures.keys()):
            p = textures[k]
            nk = self._ROLE_MAPPING.get(norm_key(k), norm_key(k))
            normalized.setdefault(nk, p)
        return normalized

    def _sanitize_node_name(self, name: str) -> str:
        sanitized = name.replace(" ", "_").replace("-", "_")
        sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        return sanitized

    def _set_file_colorspace(self, file_node: str, colorspace: str) -> None:
        """Best-effort set file node colorspace (varies with Maya config)."""
        cmds = self._maya_cmds()
        try:
            if cmds.attributeQuery("colorSpace", node=file_node, exists=True):
                cmds.setAttr(f"{file_node}.colorSpace", colorspace, type="string")
        except Exception as e:
            logger.debug(f"Failed to set {file_node}.colorSpace to {colorspace}: {e}")

    def _connect_place2d(self, place2d: str, file_node: str) -> None:
        """Connect a place2dTexture to a file node (common attributes)."""
        cmds = self._maya_cmds()
        pairs = [
            ("coverage", "coverage"),
            ("translateFrame", "translateFrame"),
            ("rotateFrame", "rotateFrame"),
            ("mirrorU", "mirrorU"),
            ("mirrorV", "mirrorV"),
            ("stagger", "stagger"),
            ("wrapU", "wrapU"),
            ("wrapV", "wrapV"),
            ("repeatUV", "repeatUV"),
            ("offset", "offset"),
            ("rotateUV", "rotateUV"),
            ("noiseUV", "noiseUV"),
            ("vertexUvOne", "vertexUvOne"),
            ("vertexUvTwo", "vertexUvTwo"),
            ("vertexUvThree", "vertexUvThree"),
            ("vertexCameraOne", "vertexCameraOne"),
            ("outUV", "uvCoord"),
            ("outUvFilterSize", "uvFilterSize"),
        ]
        for src_attr, dst_attr in pairs:
            try:
                cmds.connectAttr(f"{place2d}.{src_attr}", f"{file_node}.{dst_attr}", force=True)
            except Exception:
                # Many attrs are optional depending on node version; ignore.
                pass

    def _create_file_node(
        self,
        *,
        texture_path: Path,
        name: str,
        non_color: bool,
        alpha_is_luminance: bool,
    ) -> str:
        """Create a file texture node (with place2dTexture) and set its path."""
        cmds = self._maya_cmds()

        safe = self._sanitize_node_name(name)
        file_node = cmds.shadingNode("file", asTexture=True, name=f"{safe}_file")
        place2d = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{safe}_place2d")
        self._connect_place2d(place2d, file_node)

        cmds.setAttr(f"{file_node}.fileTextureName", str(texture_path), type="string")

        if non_color:
            # Raw is the most portable label across typical Maya configs.
            self._set_file_colorspace(file_node, "Raw")

        try:
            if cmds.attributeQuery("alphaIsLuminance", node=file_node, exists=True):
                cmds.setAttr(f"{file_node}.alphaIsLuminance", bool(alpha_is_luminance))
        except Exception:
            pass

        return file_node

    def create_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Default composite material import for strategies (optional helper)."""
        if composite.composite_type != CompositeType.MATERIAL:
            raise ValueError(f"Expected MATERIAL composite, got: {composite.composite_type}")

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        textures: dict[str, Path] = {}
        for child in composite.children:
            if not isinstance(child, CompositeAsset) or child.composite_type != CompositeType.TEXTURE:
                continue

            role_any = child.metadata.get("role") if isinstance(child.metadata, dict) else None
            role = role_any if isinstance(role_any, str) and role_any else child.name

            selected = self._select_local_asset_for_resolution(child, target_resolution)
            if selected and selected.local_path:
                textures[role] = selected.local_path

        return self.create_material_from_textures(composite.name, textures, options)

