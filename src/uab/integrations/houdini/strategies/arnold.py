"""Arnold render strategy for Houdini.

Implements material and environment light creation for Arnold (HtoA).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.models import CompositeAsset, CompositeType, StandardAsset
from uab.integrations.houdini._hou import require_hou
from uab.integrations.houdini.strategies.base import SharedHoudiniRenderStrategyUtils

logger = logging.getLogger(__name__)


class ArnoldStrategy(SharedHoudiniRenderStrategyUtils):
    """
    Arnold-specific render strategy for Houdini.

    Creates Arnold Standard Surface materials and Skydome lights
    for imported assets.

    Node Types Used:
        - arnold_materialbuilder: Material container
        - arnold::standard_surface: PBR shader
        - arnold::image: Texture loader
        - arnold::normal_map: Normal map processor
        - arnold_skydome_light: Environment light for HDRIs
    """

    @property
    def renderer_name(self) -> str:
        return "arnold"

    def get_required_texture_maps(self) -> set[str]:
        # Any one of these variants satisfies the "base color" requirement.
        return {"diffuse", "base_color", "albedo"}

    def create_environment_light(
        self, composite: CompositeAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create an Arnold Skydome light from an HDRI composite.

        Args:
            composite: The HDRI composite (must have a LOCAL leaf Asset)
            options: Creation options (unused currently)

        Returns:
            The created skydome light node (hou.Node)

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

        # Create the skydome light at /obj level
        obj = hou.node("/obj")
        light_name = self._sanitize_node_name(f"{composite.name}_skydome")

        # Create Arnold Skydome Light
        skydome = obj.createNode("arnold_skydome_light", light_name)

        # Set the HDRI texture
        skydome.parm("ar_texture").set(hdri_path)

        # Set common defaults for HDRI lighting
        skydome.parm("ar_intensity").set(1.0)
        skydome.parm("ar_exposure").set(0.0)

        # Position the node nicely in the network editor
        skydome.moveToGoodPosition()

        logger.info(f"Created Arnold skydome light: {skydome.path()}")
        return skydome

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """
        Update an existing Arnold Skydome light with a new HDRI.

        Expects options["node"] to contain the target node path or node object.

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
        node.parm("ar_texture").set(hdri_path)
        logger.info(f"Updated Arnold skydome light: {node.path()}")

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:
        """
        Create an Arnold Standard Surface material from texture paths.

        Creates a material network in /mat with:
        - Arnold Material Builder container
        - Standard Surface shader
        - Image nodes for each texture map
        - Normal map processor for normal maps

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
            # Create /mat if it doesn't exist
            mat = hou.node("/").createNode("mat", "mat")

        mat_name = f"{self._sanitize_node_name(name)}_{self.renderer_name}"
        mat_builder = mat.createNode("arnold_materialbuilder", mat_name)

        # Get the output node inside the material builder
        # Arnold Material Builder has a standard_surface and OUT node by default
        surface_shader = None
        out_node = None

        for child in mat_builder.children():
            if child.type().name() == "arnold::standard_surface":
                surface_shader = child
            elif child.type().name() == "suboutput":
                out_node = child

        # If no standard surface exists, create one
        if surface_shader is None:
            surface_shader = mat_builder.createNode(
                "arnold::standard_surface", "standard_surface1"
            )

        # Connect texture maps
        self._connect_texture_maps(mat_builder, surface_shader, normalized)

        # Connect surface shader to output if not already connected
        if out_node and surface_shader:
            out_node.setInput(0, surface_shader, 0)

        # Layout nodes nicely
        mat_builder.layoutChildren()
        mat_builder.moveToGoodPosition()

        logger.info(f"Created Arnold material: {mat_builder.path()}")
        return mat_builder

    def _connect_texture_maps(
        self,
        mat_builder: Any,  # hou.Node
        surface_shader: Any,  # hou.Node
        maps: dict[str, Path],
    ) -> None:
        """
        Create image nodes and connect them to the surface shader.

        Args:
            mat_builder: The material builder node
            surface_shader: The standard surface shader node
            maps: Dict of map_name -> texture_path
        """
        # Map semantic names to Arnold Standard Surface parameter names
        param_map = {
            "diffuse": ("base_color", None),
            "roughness": ("specular_roughness", None),
            "metallic": ("metalness", None),
            "normal": ("normal", "arnold::normal_map"),
            "ao": ("base_color", "multiply"),  # Multiply with diffuse
            "emission": ("emission_color", None),
            "opacity": ("opacity", None),
        }

        for map_name, texture_path in maps.items():
            if map_name not in param_map:
                logger.debug(f"Skipping unsupported map type: {map_name}")
                continue

            param_name, processor = param_map[map_name]

            # Create image node
            image_node = mat_builder.createNode(
                "arnold::image", f"{map_name}_tex")
            image_node.parm("filename").set(str(texture_path))

            # Handle normal maps specially
            if processor == "arnold::normal_map":
                normal_node = mat_builder.createNode(
                    "arnold::normal_map", f"{map_name}_normal"
                )
                normal_node.setInput(0, image_node, 0)
                # Connect normal map to bump input
                surface_shader.setNamedInput("normal", normal_node, 0)
            elif map_name == "ao":
                # For AO, we'd ideally multiply with diffuse, but for simplicity
                # we'll just note it's available
                logger.debug(f"AO map available at: {texture_path}")
            else:
                # Connect directly to surface shader parameter
                try:
                    surface_shader.setNamedInput(param_name, image_node, 0)
                except Exception as e:
                    logger.warning(
                        f"Could not connect {map_name} to {param_name}: {e}"
                    )

    def update_material(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """
        Update an existing Arnold material with new textures.

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

        # Update image node paths inside the material builder
        for child in node.children():
            if child.type().name() == "arnold::image":
                # Extract map name from node name (e.g., "diffuse_tex")
                child_name = child.name()
                for map_name, texture_path in available_maps.items():
                    if child_name.startswith(map_name):
                        child.parm("filename").set(texture_path)
                        logger.debug(f"Updated {child_name} to {texture_path}")

        logger.info(f"Updated Arnold material: {node.path()}")
