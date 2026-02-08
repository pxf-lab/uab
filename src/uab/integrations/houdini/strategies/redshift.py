"""Redshift render strategy for Houdini.

Implements material and environment light creation for Redshift.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.models import CompositeAsset, CompositeType, StandardAsset
from uab.integrations.houdini._hou import require_hou
from uab.integrations.houdini.strategies.base import SharedHoudiniRenderStrategyUtils

logger = logging.getLogger(__name__)


class RedshiftStrategy(SharedHoudiniRenderStrategyUtils):
    """
    Redshift-specific render strategy for Houdini.

    Creates Redshift materials and Dome lights for imported assets.

    Node Types Used:
        - rs_materialbuilder: Material container
        - redshift::StandardMaterial: PBR shader
        - redshift::TextureSampler: Texture loader
        - redshift::NormalMap: Normal map processor
        - rsLight (dome): Environment light for HDRIs
    """

    @property
    def renderer_name(self) -> str:
        return "redshift"

    def get_required_texture_maps(self) -> set[str]:
        # Any one of these variants satisfies the "base color" requirement.
        return {"diffuse", "base_color", "albedo"}

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create a Redshift Dome light from an HDRI composite.

        Args:
            composite: The HDRI composite (must have a LOCAL leaf Asset)
            options: Creation options (unused currently)

        Returns:
            The created dome light node (hou.Node)

        Raises:
            ValueError: If no local HDRI file is available
        """
        hou = require_hou()

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

        hdri_path = str(selected.local_path)

        # Create the dome light at /obj level
        obj = hou.node("/obj")
        light_name = self._sanitize_node_name(f"{composite.name}_dome")

        # Create Redshift Light (dome type)
        dome = obj.createNode("rsLight", light_name)

        # Set light type to Dome (environment)
        dome.parm("RSL_lightType").set("dome")

        # Set the HDRI texture
        # Redshift dome lights use the background texture parameter
        dome.parm("RSL_dome_tex0").set(hdri_path)

        # Set common defaults
        dome.parm("RSL_intensityMultiplier").set(1.0)
        dome.parm("RSL_exposure").set(0.0)

        # Position the node nicely
        dome.moveToGoodPosition()

        logger.info(f"Created Redshift dome light: {dome.path()}")
        return dome

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """
        Update an existing Redshift Dome light with a new HDRI.

        Args:
            asset: The HDRI asset
            options: Must contain "node" key with target node

        Raises:
            ValueError: If no node specified or HDRI path not found
        """
        hou = require_hou()

        self._log_import(asset, "Updating environment light")

        node = options.get("node")
        if node is None:
            raise ValueError("No target node specified in options")

        if isinstance(node, str):
            node = hou.node(node)

        if node is None:
            raise ValueError("Target node not found")

        hdri_path = self._get_hdri_path(asset)
        if not hdri_path:
            raise ValueError(f"No HDRI file found for asset: {asset.name}")

        # Update the texture path
        node.parm("RSL_dome_tex0").set(hdri_path)
        logger.info(f"Updated Redshift dome light: {node.path()}")

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        """
        Create a Redshift StandardMaterial from texture paths.

        Creates a material network in /mat with:
        - RS Material Builder container
        - StandardMaterial shader
        - TextureSampler nodes for each texture map
        - NormalMap processor for normal maps

        Args:
            name: Material display name
            textures: Dict of role/map key -> local texture path
            options: Creation options (unused currently)

        Returns:
            The created material builder node (hou.Node)

        Raises:
            ValueError: If no texture maps found
        """
        hou = require_hou()

        normalized = self._normalize_texture_keys(textures)
        if not normalized:
            raise ValueError(f"No texture maps found for material: {name}")

        # Create material builder in /mat
        mat = hou.node("/mat")
        if mat is None:
            mat = hou.node("/").createNode("mat", "mat")

        mat_name = f"{self._sanitize_node_name(name)}_{self.renderer_name}"
        mat_builder = mat.createNode("rs_materialbuilder", mat_name)

        # Get or create the standard material inside the builder
        standard_mat = None
        out_node = None

        for child in mat_builder.children():
            if child.type().name() == "redshift::StandardMaterial":
                standard_mat = child
            elif child.type().name() == "redshift_material":
                out_node = child

        # Create standard material if it doesn't exist
        if standard_mat is None:
            standard_mat = mat_builder.createNode(
                "redshift::StandardMaterial", "StandardMaterial1"
            )

        # Connect texture maps
        self._connect_texture_maps(mat_builder, standard_mat, normalized)

        # Connect to output
        if out_node and standard_mat:
            out_node.setInput(0, standard_mat, 0)

        # Layout nodes
        mat_builder.layoutChildren()
        mat_builder.moveToGoodPosition()

        logger.info(f"Created Redshift material: {mat_builder.path()}")
        return mat_builder

    def _connect_texture_maps(
        self,
        mat_builder: Any,  # hou.Node
        standard_mat: Any,  # hou.Node
        maps: dict[str, Path],
    ) -> None:
        """
        Create texture sampler nodes and connect them to the standard material.

        Args:
            mat_builder: The material builder node
            standard_mat: The StandardMaterial shader node
            maps: Dict of map_name -> texture_path
        """
        # Map semantic names to Redshift StandardMaterial input names
        param_map = {
            "diffuse": ("diffuse_color", None),
            "roughness": ("refl_roughness", None),
            "metallic": ("metalness", None),
            "normal": ("bump_input", "redshift::NormalMap"),
            "ao": ("overall_color", "multiply"),
            "emission": ("emission_color", None),
            "opacity": ("opacity_color", None),
        }

        for map_name, texture_path in maps.items():
            if map_name not in param_map:
                logger.debug(f"Skipping unsupported map type: {map_name}")
                continue

            param_name, processor = param_map[map_name]

            # Create texture sampler node
            tex_node = mat_builder.createNode(
                "redshift::TextureSampler", f"{map_name}_tex"
            )
            tex_node.parm("tex0").set(str(texture_path))

            # Handle normal maps specially
            if processor == "redshift::NormalMap":
                normal_node = mat_builder.createNode(
                    "redshift::NormalMap", f"{map_name}_normal"
                )
                normal_node.setInput(0, tex_node, 0)
                try:
                    standard_mat.setNamedInput(param_name, normal_node, 0)
                except Exception as e:
                    logger.warning(f"Could not connect normal map: {e}")
            elif map_name == "ao":
                # AO handling - log availability for now
                logger.debug(f"AO map available at: {texture_path}")
            else:
                # Connect directly
                try:
                    standard_mat.setNamedInput(param_name, tex_node, 0)
                except Exception as e:
                    logger.warning(
                        f"Could not connect {map_name} to {param_name}: {e}"
                    )

    def update_material(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """
        Update an existing Redshift material with new textures.

        Args:
            asset: The texture asset
            options: Must contain "node" key with target material node
        """
        hou = require_hou()

        self._log_import(asset, "Updating material")

        node = options.get("node")
        if node is None:
            raise ValueError("No target node specified in options")

        if isinstance(node, str):
            node = hou.node(node)

        if node is None:
            raise ValueError("Target node not found")

        available_maps = self._get_available_maps(asset)

        # Update texture sampler paths inside the material builder
        for child in node.children():
            if child.type().name() == "redshift::TextureSampler":
                child_name = child.name()
                for map_name, texture_path in available_maps.items():
                    if child_name.startswith(map_name):
                        child.parm("tex0").set(texture_path)
                        logger.debug(f"Updated {child_name} to {texture_path}")

        logger.info(f"Updated Redshift material: {node.path()}")
