"""Arnold render strategy for Maya (mtoa)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.models import CompositeAsset, CompositeType, StandardAsset
from uab.integrations.maya.strategies.base import SharedMayaRenderStrategyUtils

logger = logging.getLogger(__name__)


class ArnoldStrategy(SharedMayaRenderStrategyUtils):
    """Arnold-specific material and environment light creation in Maya."""

    @property
    def renderer_name(self) -> str:
        return "arnold"

    def get_required_texture_maps(self) -> set[str]:
        # Any one of these variants satisfies the base color requirement.
        return {"diffuse", "base_color", "albedo"}

    # ENVIRONMENT LIGHT

    def _ensure_mtoa_loaded(self) -> None:
        cmds = self._maya_cmds()
        try:
            if not cmds.pluginInfo("mtoa", query=True, loaded=True):
                if cmds.pluginInfo("mtoa", query=True, available=True):
                    cmds.loadPlugin("mtoa")
        except Exception:
            logger.warning("Failed to load mtoa plugin")

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        self._ensure_mtoa_loaded()
        cmds = self._maya_cmds()

        if composite.composite_type != CompositeType.HDRI:
            raise ValueError(
                f"Expected HDRI composite, got: {composite.composite_type}"
            )

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        selected = self._select_local_asset_for_resolution(
            composite, target_resolution
        )
        if not selected or not selected.local_path:
            raise ValueError(f"No local HDRI available for: {composite.name}")

        hdri_path = selected.local_path

        base = self._sanitize_node_name(composite.name)
        shape = cmds.shadingNode(
            "aiSkyDomeLight",
            asLight=True,
            name=f"{base}_skydomeShape",
        )

        # Get transform (for nicer scene organization)
        transform = shape
        try:
            parent = cmds.listRelatives(shape, parent=True, fullPath=True)
            if parent:
                transform = parent[0]
        except Exception:
            logger.warning(
                "Failed to get transform for skydome light, using shape as transform")

        # Create file node and connect to skydome color
        file_node = self._create_file_node(
            texture_path=hdri_path,
            name=f"{base}_hdri",
            non_color=True,
            alpha_is_luminance=False,
        )
        try:
            cmds.connectAttr(f"{file_node}.outColor",
                             f"{shape}.color", force=True)
        except Exception as e:
            raise ValueError(
                f"Failed to connect HDRI to skydome light: {e}") from e

        # Common defaults (best-effort; attribute names may vary)
        for attr, value in (
            ("aiExposure", 0.0),
            ("aiSamples", 1),
            ("intensity", 1.0),
        ):
            try:
                if cmds.attributeQuery(attr, node=shape, exists=True):
                    cmds.setAttr(f"{shape}.{attr}", value)
            except Exception:
                pass

        logger.info(f"Created Arnold skydome light: {transform}")
        return transform

    def update_environment_light(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        self._ensure_mtoa_loaded()
        cmds = self._maya_cmds()

        node = options.get("node")
        if not isinstance(node, str) or not node:
            raise ValueError(
                "update_environment_light requires options['node'] as a Maya node name")

        # Resolve target shape
        shape = node
        try:
            if cmds.nodeType(node) != "aiSkyDomeLight":
                shapes = cmds.listRelatives(
                    node, shapes=True, fullPath=False) or []
                shape = next((s for s in shapes if cmds.nodeType(
                    s) == "aiSkyDomeLight"), node)
        except Exception:
            shape = node

        hdri_path = None
        if asset.local_path and asset.local_path.exists():
            if asset.local_path.is_file():
                hdri_path = asset.local_path
            elif asset.local_path.is_dir():
                for f in asset.local_path.iterdir():
                    if f.suffix.lower() in {".hdr", ".exr", ".hdri"}:
                        hdri_path = f
                        break

        if hdri_path is None:
            raise ValueError(f"No HDRI file found for asset: {asset.name}")

        # Find existing file node connection, else create one
        file_nodes = cmds.listConnections(
            f"{shape}.color", source=True, destination=False) or []
        file_node = next(
            (n for n in file_nodes if cmds.nodeType(n) == "file"), None)
        if file_node is None:
            file_node = self._create_file_node(
                texture_path=hdri_path,
                name=f"{self._sanitize_node_name(asset.name)}_hdri",
                non_color=True,
                alpha_is_luminance=False,
            )
            cmds.connectAttr(f"{file_node}.outColor",
                             f"{shape}.color", force=True)

        cmds.setAttr(f"{file_node}.fileTextureName",
                     str(hdri_path), type="string")

    # MATERIAL

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        self._ensure_mtoa_loaded()
        cmds = self._maya_cmds()

        normalized = self._normalize_texture_keys(textures)
        if not normalized:
            raise ValueError(f"No texture maps found for material: {name}")

        base = self._sanitize_node_name(name)
        shader = cmds.shadingNode(
            "aiStandardSurface", asShader=True, name=f"{base}_aiStandardSurface"
        )

        # Ensure base weight is on
        try:
            if cmds.attributeQuery("base", node=shader, exists=True):
                cmds.setAttr(f"{shader}.base", 1.0)
        except Exception:
            pass

        sg = cmds.sets(
            renderable=True,
            noSurfaceShader=True,
            empty=True,
            name=f"{base}_SG",
        )
        try:
            cmds.connectAttr(f"{shader}.outColor",
                             f"{sg}.surfaceShader", force=True)
        except Exception as e:
            raise ValueError(
                f"Failed to connect shader to shading group: {e}") from e

        # Map roles to Arnold Standard Surface attrs
        for role, tex_path in normalized.items():
            if role == "diffuse":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_diffuse",
                    non_color=False,
                    alpha_is_luminance=False,
                )
                cmds.connectAttr(f"{file_node}.outColor",
                                 f"{shader}.baseColor", force=True)
                continue

            if role == "roughness":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_roughness",
                    non_color=True,
                    alpha_is_luminance=True,
                )
                cmds.connectAttr(
                    f"{file_node}.outAlpha", f"{shader}.specularRoughness", force=True
                )
                continue

            if role == "metallic":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_metallic",
                    non_color=True,
                    alpha_is_luminance=True,
                )
                cmds.connectAttr(f"{file_node}.outAlpha",
                                 f"{shader}.metalness", force=True)
                continue

            if role == "normal":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_normal",
                    non_color=True,
                    alpha_is_luminance=False,
                )
                normal_node = cmds.shadingNode(
                    "aiNormalMap", asUtility=True, name=f"{base}_aiNormalMap"
                )
                cmds.connectAttr(f"{file_node}.outColor",
                                 f"{normal_node}.input", force=True)
                cmds.connectAttr(
                    f"{normal_node}.outValue", f"{shader}.normalCamera", force=True
                )
                continue

            if role == "displacement":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_displacement",
                    non_color=True,
                    alpha_is_luminance=True,
                )
                disp = cmds.shadingNode(
                    "displacementShader", asShader=True, name=f"{base}_displacementShader"
                )
                cmds.connectAttr(f"{file_node}.outAlpha",
                                 f"{disp}.displacement", force=True)
                cmds.connectAttr(f"{disp}.displacement",
                                 f"{sg}.displacementShader", force=True)
                continue

            if role == "opacity":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_opacity",
                    non_color=True,
                    alpha_is_luminance=True,
                )
                # opacity is RGB; drive all channels from the scalar alpha
                for ch in ("R", "G", "B"):
                    try:
                        cmds.connectAttr(
                            f"{file_node}.outAlpha", f"{shader}.opacity{ch}", force=True
                        )
                    except Exception:
                        pass
                continue

            if role == "emission":
                file_node = self._create_file_node(
                    texture_path=tex_path,
                    name=f"{base}_emission",
                    non_color=False,
                    alpha_is_luminance=False,
                )
                try:
                    cmds.connectAttr(
                        f"{file_node}.outColor", f"{shader}.emissionColor", force=True
                    )
                    if cmds.attributeQuery("emission", node=shader, exists=True):
                        cmds.setAttr(f"{shader}.emission", 1.0)
                except Exception:
                    pass
                continue

            # Optional/unknown roles: keep import resilient; strategy can be extended later.
            logger.debug(
                f"[Arnold/Maya] Unsupported map role '{role}' for material '{name}'")

        logger.info(f"Created Arnold material: {shader}")
        return {"shader": shader, "shading_group": sg}

    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Best-effort update of an existing Arnold material.

        Not currently used because MayaIntegration does not enable replace-selection.
        """
        node = options.get("node")
        if not isinstance(node, str) or not node:
            raise ValueError(
                "update_material requires options['node'] as a Maya node name")

        # Placeholder: intentionally minimal to avoid fragile heuristics.
        logger.info(
            f"update_material is not implemented for Maya Arnold (node={node})")
        return None
