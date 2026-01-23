"""Karma render strategy for Houdini.

Implements material and environment light creation for Karma (Solaris/USD).
"""

from __future__ import annotations

import logging
from typing import Any

from uab.core.models import StandardAsset, AssetType
from uab.integrations.houdini.strategies.base import SharedHoudiniRenderStrategyUtils

logger = logging.getLogger(__name__)


class KarmaStrategy(SharedHoudiniRenderStrategyUtils):
    """
    Karma-specific render strategy for Houdini.

    Creates Karma/USD dome lights and MaterialX-based materials
    for imported assets using Solaris LOPs.

    Node Types Used:
        - domelight: USD Dome Light LOP for HDRIs (in /stage)
        - materiallibrary: Material container LOP
        - mtlxstandard_surface: MaterialX PBR shader
        - mtlximage: MaterialX texture loader
        - mtlxnormalmap: MaterialX normal map processor
    """

    @property
    def renderer_name(self) -> str:
        return "karma"

    def create_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create a Karma/USD Dome light from an HDRI asset.

        Creates a domelight LOP in /stage with the HDRI texture set.

        Args:
            asset: The HDRI asset (must have local_path set)
            options: Creation options (unused currently)

        Returns:
            The created domelight node (hou.Node)

        Raises:
            ValueError: If asset is not an HDRI or has no local path
        """
        import hou

        self._log_import(asset, "Creating environment light")

        hdri_path = self._get_hdri_path(asset)
        if not hdri_path:
            raise ValueError(f"No HDRI file found for asset: {asset.name}")

        stage = hou.node("/stage")
        if stage is None:
            stage = hou.node("/").createNode("stage", "stage")

        light_name = self._sanitize_node_name(f"{asset.name}_domelight")

        domelight = stage.createNode("domelight", light_name)

        # Set the HDRI texture using USD attribute
        # xn__inputstexturefile_r3ah is the mangled name for inputs:texture:file
        tex_parm = domelight.parm("xn__inputstexturefile_r3ah")
        if tex_parm:
            tex_parm.set(hdri_path)
        else:
            # Fallback to old param names
            alt_parms = ["texture:file", "texturefile", "ar_texture"]
            for parm_name in alt_parms:
                parm = domelight.parm(parm_name)
                if parm:
                    parm.set(hdri_path)
                    break
            else:
                logger.warning(
                    f"Could not find texture parameter on domelight. "
                    f"Available parms: {[p.name() for p in domelight.parms()]}"
                )

        intensity_parm = domelight.parm("xn__inputsintensity_i0a")
        if intensity_parm:
            intensity_parm.set(1.0)

        exposure_parm = domelight.parm("xn__inputsexposure_qta")
        if exposure_parm:
            exposure_parm.set(0.0)

        domelight.moveToGoodPosition()

        logger.info(f"Created Karma dome light: {domelight.path()}")
        return domelight

    def update_environment_light(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """
        Update an existing Karma dome light with a new HDRI.

        Expects options["node"] to contain the target node path or node object.

        Args:
            asset: The HDRI asset
            options: Must contain "node" key with target node

        Raises:
            ValueError: If no node specified or HDRI path not found
        """
        import hou

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

        tex_parm = node.parm("xn__inputstexturefile_r3ah")
        if tex_parm:
            tex_parm.set(hdri_path)
        else:
            # Try old param names
            alt_parms = ["texture:file", "texturefile"]
            for parm_name in alt_parms:
                parm = node.parm(parm_name)
                if parm:
                    parm.set(hdri_path)
                    break

        logger.info(f"Updated Karma dome light: {node.path()}")

    def create_material(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> Any:
        """
        Create a MaterialX Standard Surface material from a texture asset.

        Creates a material network in /stage using MaterialX nodes:
        - materiallibrary container
        - mtlxstandard_surface shader
        - mtlximage nodes for each texture map
        - mtlxnormalmap processor for normal maps

        Args:
            asset: The texture asset (must have local_path set)
            options: Creation options (unused currently)

        Returns:
            The created materiallibrary node (hou.Node)

        Raises:
            ValueError: If no texture maps found for asset
        """
        import hou

        self._log_import(asset, "Creating material")

        available_maps = self._get_available_maps(asset)
        if not available_maps:
            raise ValueError(f"No texture maps found for asset: {asset.name}")

        # Get or create /stage
        stage = hou.node("/stage")
        if stage is None:
            stage = hou.node("/").createNode("stage", "stage")

        mat_name = self._get_material_name(asset)

        mat_lib = stage.createNode("materiallibrary", mat_name)

        mat_lib.parm("materials").set(1)

        mat_context = mat_lib
        for child in mat_lib.children():
            if child.type().category().name() == "Vop":
                mat_context = child
                break

        surface_shader = mat_context.createNode(
            "mtlxstandard_surface", "mtlxstandard_surface1"
        )

        collect_node = None
        for child in mat_context.children():
            if child.type().name() == "collect":
                collect_node = child
                break

        if collect_node is None:
            collect_node = mat_context.createNode("collect", "collect1")

        self._connect_texture_maps(mat_context, surface_shader, available_maps)

        collect_node.setInput(0, surface_shader, 0)

        mat_lib.parm("matpathprefix").set(f"/materials/{mat_name}")

        mat_context.layoutChildren()
        mat_lib.moveToGoodPosition()

        logger.info(f"Created Karma MaterialX material: {mat_lib.path()}")
        return mat_lib

    def _connect_texture_maps(
        self,
        mat_context: Any,  # hou.Node
        surface_shader: Any,  # hou.Node
        maps: dict[str, str],
    ) -> None:
        """
        Create MaterialX image nodes and connect them to the surface shader.

        Args:
            mat_context: The material context node
            surface_shader: The mtlxstandard_surface shader node
            maps: Dict of map_name -> texture_path
        """
        param_map = {
            "diffuse": ("base_color", None),
            "roughness": ("specular_roughness", None),
            "metalness": ("metalness", None),
            "normal": ("normal", "mtlxnormalmap"),
            "ao": ("base_color", "multiply"),  # Would multiply with diffuse
            "emission": ("emission_color", None),
            "opacity": ("opacity", None),
        }

        for map_name, texture_path in maps.items():
            if map_name not in param_map:
                logger.debug(f"Skipping unsupported map type: {map_name}")
                continue

            param_name, processor = param_map[map_name]

            image_node = mat_context.createNode("mtlximage", f"{map_name}_tex")
            image_node.parm("file").set(texture_path)

            if map_name in ["roughness", "metalness", "normal", "ao", "opacity"]:
                colorspace_parm = image_node.parm("signature")
                if colorspace_parm:
                    colorspace_parm.set("default")

            if processor == "mtlxnormalmap":
                normal_node = mat_context.createNode(
                    "mtlxnormalmap", f"{map_name}_normal"
                )
                normal_node.setInput(0, image_node, 0)
                try:
                    surface_shader.setNamedInput(param_name, normal_node, 0)
                except Exception as e:
                    logger.warning(f"Could not connect normal map: {e}")
            elif map_name == "ao":
                logger.debug(f"AO map available at: {texture_path}")
            else:
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
        Update an existing Karma MaterialX material with new textures.

        Args:
            asset: The texture asset
            options: Must contain "node" key with target material node
        """
        import hou

        self._log_import(asset, "Updating material")

        node = options.get("node")
        if node is None:
            raise ValueError("No target node specified in options")

        if isinstance(node, str):
            node = hou.node(node)

        if node is None:
            raise ValueError("Target node not found")

        available_maps = self._get_available_maps(asset)

        mat_context = node
        for child in node.children():
            if child.type().category().name() == "Vop":
                mat_context = child
                break

        def update_image_nodes(context: Any) -> None:
            for child in context.children():
                if child.type().name() == "mtlximage":
                    child_name = child.name()
                    for map_name, texture_path in available_maps.items():
                        if child_name.startswith(map_name):
                            child.parm("file").set(texture_path)
                            logger.debug(
                                f"Updated {child_name} to {texture_path}")
                # Recurse into subnets
                if child.children():
                    update_image_nodes(child)

        update_image_nodes(mat_context)

        logger.info(f"Updated Karma material: {node.path()}")
