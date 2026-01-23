"""Houdini host integration for Universal Asset Browser.

Provides asset import functionality for Houdini, with support for
multiple renderers (Arnold, Redshift, Karma) through the RenderStrategy pattern.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from uab.core.interfaces import HostIntegration, RenderStrategy
from uab.core.models import StandardAsset, AssetType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class HoudiniIntegration(HostIntegration):
    """
    Houdini-specific host integration.

    Handles importing assets into Houdini scenes, detecting the active
    renderer, and delegating material/light creation to renderer-specific
    strategies.

    Usage:
        from uab.integrations.houdini import HoudiniIntegration

        integration = HoudiniIntegration()
        integration.import_asset(asset, options)

    The integration auto-detects available renderers and selects the
    appropriate strategy based on scene configuration.
    """

    # Renderers supported by UAB with available strategies
    _SUPPORTED_RENDERERS = ["arnold", "redshift", "karma"]

    def __init__(self) -> None:
        """Initialize the Houdini integration with renderer strategies."""
        self._strategies: dict[str, RenderStrategy] = {}
        self._load_strategies()

    def _load_strategies(self) -> None:
        """Load renderer strategies for available renderers."""
        from uab.integrations.houdini.strategies import (
            KarmaStrategy,
        )

        # Register all known strategies
        # They'll only be used if the renderer is actually available
        self._strategies = {
            "karma": KarmaStrategy(),
        }

        logger.debug(f"Loaded strategies: {list(self._strategies.keys())}")

    @property
    def uab_supported_renderers(self) -> list[str]:
        """Return the list of renderers that UAB supports."""
        return self._SUPPORTED_RENDERERS.copy()

    def get_host_available_renderers(self) -> list[str]:
        """
        Return renderers that are installed and available in Houdini.

        Checks for the presence of renderer-specific node types.

        Returns:
            List of available renderer identifiers
        """
        import hou

        available = []

        # Check for Arnold (HtoA)
        try:
            if hou.nodeType(hou.objNodeTypeCategory(), "arnold_skydome_light"):
                available.append("arnold")
        except Exception:
            pass

        # Check for Redshift
        try:
            if hou.nodeType(hou.objNodeTypeCategory(), "rsLight"):
                available.append("redshift")
        except Exception:
            pass

        # Check for Karma (always available in recent Houdini)
        try:
            if hou.nodeType(hou.lopNodeTypeCategory(), "karmacameraproperties"):
                available.append("karma")
        except Exception:
            pass

        logger.debug(f"Available renderers: {available}")
        return available

    def get_active_renderer(self) -> str:
        """
        Detect and return the active renderer from the Houdini scene.

        Detection order:
        1. Check for renderer-specific ROPs in /out
        2. Check for renderer-specific lights in /obj
        3. Fall back to first available supported renderer
        4. Return "karma" if nothing else found

        Returns:
            Renderer identifier (e.g., "arnold", "redshift", "karma")
        """
        import hou

        # Check ROPs in /out for renderer hints
        out = hou.node("/out")
        if out:
            for child in out.children():
                node_type = child.type().name().lower()
                if "arnold" in node_type:
                    logger.debug("Detected Arnold from ROP")
                    return "arnold"
                elif "redshift" in node_type or node_type.startswith("rs"):
                    logger.debug("Detected Redshift from ROP")
                    return "redshift"
                elif "karma" in node_type:
                    logger.debug("Detected Karma from ROP")
                    return "karma"

        # Check lights in /obj
        obj = hou.node("/obj")
        if obj:
            for child in obj.children():
                node_type = child.type().name().lower()
                if "arnold" in node_type:
                    logger.debug("Detected Arnold from light")
                    return "arnold"
                elif "rslight" in node_type or "redshift" in node_type:
                    logger.debug("Detected Redshift from light")
                    return "redshift"

        # Fall back to first available supported renderer
        available = self.get_host_available_renderers()
        for renderer in self._SUPPORTED_RENDERERS:
            if renderer in available:
                logger.debug(f"Falling back to first available: {renderer}")
                return renderer

        # Ultimate fallback
        logger.debug("No renderer detected, defaulting to karma")
        return "karma"

    @property
    def supports_replace_selection(self) -> bool:
        """Houdini supports updating selected nodes with new asset data."""
        return True

    def get_node_label_for_asset_type(self, asset_type: AssetType) -> str:
        """
        Return Houdini-specific node labels for asset types.

        Args:
            asset_type: The type of asset

        Returns:
            Human-readable label used in context menus
        """
        labels = {
            AssetType.HDRI: "Environment Light",
            AssetType.TEXTURE: "Material",
            AssetType.MODEL: "Geometry",
        }
        return labels.get(asset_type, asset_type.value.title())

    def _get_strategy(self, renderer: str | None = None) -> RenderStrategy | None:
        """
        Get the render strategy for the specified or active renderer.

        Args:
            renderer: Renderer identifier, or None to use active renderer

        Returns:
            The RenderStrategy instance, or None if not available
        """
        if renderer is None:
            renderer = self.get_active_renderer()

        strategy = self._strategies.get(renderer)
        if strategy is None:
            logger.warning(f"No strategy available for renderer: {renderer}")

        return strategy

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """
        Import an asset into the Houdini scene.

        Creates appropriate nodes based on asset type:
        - HDRI: Creates environment light via renderer strategy
        - TEXTURE: Creates material via renderer strategy
        - MODEL: Creates geometry node with File SOP

        All operations are wrapped in an undo group.

        Args:
            asset: The asset to import (must have local_path for LOCAL assets)
            options: Import options (renderer, etc.)

        Raises:
            ValueError: If asset cannot be imported (missing path, unsupported type)
        """
        import hou

        logger.info(f"Importing asset: {asset.name} (type={asset.type.value})")

        renderer = options.get("renderer") or self.get_active_renderer()

        with hou.undos.group(f"UAB Import: {asset.name}"):
            if asset.type == AssetType.HDRI:
                self._import_hdri(asset, renderer, options)
            elif asset.type == AssetType.TEXTURE:
                self._import_texture(asset, renderer, options)
            elif asset.type == AssetType.MODEL:
                self._import_model(asset, options)
            else:
                raise ValueError(f"Unsupported asset type: {asset.type}")

    def _import_hdri(
        self, asset: StandardAsset, renderer: str, options: dict[str, Any]
    ) -> None:
        """Import an HDRI asset as an environment light."""
        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        strategy.create_environment_light(asset, options)

    def _import_texture(
        self, asset: StandardAsset, renderer: str, options: dict[str, Any]
    ) -> None:
        """Import a texture asset as a material."""
        import hou

        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        material = strategy.create_material(asset, options)

        if options.get("create_preview_geo", False):
            self._create_preview_geometry(asset, material)

    def _import_model(
        self, asset: StandardAsset, options: dict[str, Any]
    ) -> None:
        """Import a 3D model asset."""
        import hou

        if not asset.local_path:
            raise ValueError(f"Asset {asset.name} has no local path")

        geo_path = self._find_geometry_file(asset)
        if not geo_path:
            raise ValueError(f"No geometry file found for asset: {asset.name}")

        obj = hou.node("/obj")
        geo_name = self._sanitize_node_name(asset.name)
        geo_node = obj.createNode("geo", geo_name)

        for child in geo_node.children():
            if child.name() == "file1":
                child.destroy()

        file_sop = geo_node.createNode("file", "import")
        file_sop.parm("file").set(geo_path)

        file_sop.setDisplayFlag(True)
        file_sop.setRenderFlag(True)

        geo_node.moveToGoodPosition()

        logger.info(f"Created geometry node: {geo_node.path()}")

    def _find_geometry_file(self, asset: StandardAsset) -> str | None:
        """Find the geometry file path for a model asset."""
        from pathlib import Path

        if not asset.local_path:
            return None

        files = asset.metadata.get("files", {})
        if "geometry" in files:
            return str(asset.local_path / files["geometry"])
        if "model" in files:
            return str(asset.local_path / files["model"])

        # If local_path is a file, use it directly
        if asset.local_path.is_file():
            return str(asset.local_path)

        # Search for common geometry formats
        geo_extensions = [".obj", ".fbx", ".abc",
                          ".usd", ".usda", ".usdc", ".gltf", ".glb"]
        if asset.local_path.is_dir():
            for ext in geo_extensions:
                for f in asset.local_path.iterdir():
                    if f.suffix.lower() == ext:
                        return str(f)

        return None

    def _create_preview_geometry(self, asset: StandardAsset, material: Any) -> None:
        """Create a preview sphere with the material assigned."""
        import hou

        obj = hou.node("/obj")
        geo_name = self._sanitize_node_name(f"{asset.name}_preview")
        geo_node = obj.createNode("geo", geo_name)

        sphere = geo_node.createNode("sphere", "sphere")
        sphere.parm("type").set(2)  # Polygon mesh
        sphere.parm("rows").set(24)
        sphere.parm("cols").set(48)

        mat_sop = geo_node.createNode("material", "material")
        mat_sop.setInput(0, sphere)
        mat_sop.parm("shop_materialpath1").set(material.path())

        mat_sop.setDisplayFlag(True)
        mat_sop.setRenderFlag(True)

        geo_node.layoutChildren()
        geo_node.moveToGoodPosition()

        logger.info(f"Created preview geometry: {geo_node.path()}")

    def _sanitize_node_name(self, name: str) -> str:
        """Sanitize a string for use as a Houdini node name."""
        sanitized = name.replace(" ", "_").replace("-", "_")
        sanitized = "".join(c if c.isalnum() or c ==
                            "_" else "_" for c in sanitized)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        return sanitized

    def update_selection(self, asset: StandardAsset) -> None:
        """
        Update the currently selected node with the asset.

        If a compatible node is selected (environment light or material),
        update it with the new asset data.

        Args:
            asset: The asset to apply to the selection
        """
        import hou

        logger.info(f"Updating selection with asset: {asset.name}")

        selected = hou.selectedNodes()
        if not selected:
            logger.warning("No nodes selected")
            return

        node = selected[0]
        renderer = self.get_active_renderer()
        strategy = self._get_strategy(renderer)

        if strategy is None:
            logger.warning(f"No strategy for renderer: {renderer}")
            return

        with hou.undos.group(f"UAB Update: {asset.name}"):
            node_type = node.type().name().lower()

            if asset.type == AssetType.HDRI:
                if "skydome" in node_type or "rslight" in node_type or "domelight" in node_type:
                    strategy.update_environment_light(asset, {"node": node})
                else:
                    logger.warning(
                        f"Selected node {node.name()} is not an environment light"
                    )

            elif asset.type == AssetType.TEXTURE:
                if "material" in node_type:
                    strategy.update_material(asset, {"node": node})
                else:
                    logger.warning(
                        f"Selected node {node.name()} is not a material"
                    )
