"""Houdini host integration for Universal Asset Browser.

Provides asset import functionality for Houdini, with support for
multiple renderers (Arnold, Redshift, Karma) through the RenderStrategy pattern.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from uab.core.interfaces import HostIntegration, RenderStrategy
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
        from uab.integrations.houdini.strategies.karma import KarmaStrategy

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

    def import_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """
        Import a composite asset into Houdini.

        Wraps the operation in an undo group and dispatches based on composite_type.
        """
        # Best-effort undo grouping: only available in Houdini.
        try:
            import hou  # type: ignore
        except Exception:
            logger.debug("Houdini 'hou' module not available; importing without undo group")
            return super().import_composite(composite, options)

        logger.info(
            f"Importing composite: {composite.name} (type={composite.composite_type.value})"
        )

        with hou.undos.group(f"UAB Import: {composite.name}"):
            return super().import_composite(composite, options)

    def _import_hdri(
        self, asset: StandardAsset, renderer: str, options: dict[str, Any]
    ) -> None:
        """Import an HDRI asset as an environment light."""
        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        hdri_path = self._find_hdri_file(asset)
        if not hdri_path:
            raise ValueError(f"No HDRI file found for asset: {asset.name}")

        # Wrap single HDRI file into a synthetic composite for the new strategy API.
        leaf = Asset(
            id=asset.id,
            source=asset.source,
            external_id=asset.external_id,
            name=hdri_path.name,
            asset_type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_path,
            remote_url=None,
            thumbnail_url=asset.thumbnail_url or None,
            thumbnail_path=asset.thumbnail_path,
            file_size=None,
            metadata=asset.metadata.copy() if isinstance(asset.metadata, dict) else {},
        )

        composite = CompositeAsset(
            id=asset.id,
            source=asset.source,
            external_id=asset.external_id or asset.id,
            name=asset.name,
            composite_type=CompositeType.HDRI,
            thumbnail_url=asset.thumbnail_url or None,
            thumbnail_path=asset.thumbnail_path,
            metadata={},
            children=[leaf],
        )

        strategy.create_environment_light(composite, options)

    def _import_texture(
        self, asset: StandardAsset, renderer: str, options: dict[str, Any]
    ) -> None:
        """Import a texture asset as a material."""
        import hou

        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        textures = self._collect_standard_asset_textures(asset)
        material = strategy.create_material_from_textures(asset.name, textures, options)

        if options.get("create_preview_geo", False):
            self._create_preview_geometry(asset, material)

    def _import_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """
        Import a MATERIAL composite by traversing its texture children.

        TEXTURE composites are treated as a one-map MATERIAL import.

        Picks best-available LOCAL textures for the requested resolution and
        validates required maps via the active render strategy.
        """
        if composite.composite_type not in (CompositeType.MATERIAL, CompositeType.TEXTURE):
            raise ValueError(
                f"Expected MATERIAL or TEXTURE composite, got: {composite.composite_type}"
            )

        renderer = options.get("renderer") or self.get_active_renderer()
        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        material_name = composite.name
        texture_nodes: list[CompositeAsset]
        if composite.composite_type == CompositeType.MATERIAL:
            texture_nodes = [
                c
                for c in composite.children
                if isinstance(c, CompositeAsset) and c.composite_type == CompositeType.TEXTURE
            ]
        else:
            material_name = self._guess_material_name_from_texture_composite(composite)
            texture_nodes = [composite]

        texture_paths: dict[str, Path] = {}
        missing_maps: set[str] = set()
        resolution_mismatches: dict[str, str | None] = {}

        for child in texture_nodes:

            role: str | None = None
            if isinstance(child.metadata, dict):
                role_any = child.metadata.get("role") or child.metadata.get("map_type")
                if isinstance(role_any, str) and role_any:
                    role = role_any
            if not role:
                role = child.name

            selected = self._get_asset_for_resolution(child, target_resolution)
            if not selected or not selected.local_path:
                missing_maps.add(role)
                continue

            texture_paths[role] = selected.local_path

            if target_resolution:
                found_res: str | None = None
                if isinstance(selected.metadata, dict):
                    res_any = selected.metadata.get("resolution")
                    if isinstance(res_any, str) and res_any:
                        found_res = res_any
                if found_res != target_resolution:
                    resolution_mismatches[role] = found_res

        # Validate required maps (variants: any one satisfies requirement).
        required_variants = strategy.get_required_texture_maps()
        if required_variants and not any(k in texture_paths for k in required_variants):
            pretty = "/".join(sorted(required_variants))
            raise ValueError(
                f"Missing required texture map (any of): {pretty}. "
                f"Available: {', '.join(sorted(texture_paths.keys())) or '(none)'}"
            )

        optional = strategy.get_optional_texture_maps()
        missing_optional = sorted({k for k in optional if k not in texture_paths})

        # Log missing optional maps only (required missing already raises).
        if missing_optional:
            logger.info(
                f"Missing optional textures for {material_name}: {', '.join(missing_optional)}"
            )

        # Log missing maps that weren't explicitly categorized.
        uncategorized_missing = sorted(
            m for m in missing_maps if m not in required_variants and m not in optional
        )
        if uncategorized_missing:
            logger.info(
                f"Missing textures for {material_name}: {', '.join(uncategorized_missing)}"
            )

        if target_resolution and resolution_mismatches:
            mismatch_str = ", ".join(
                f"{role}={res or 'unknown'}" for role, res in sorted(resolution_mismatches.items())
            )
            logger.warning(
                f"Requested resolution {target_resolution} but using different resolutions: {mismatch_str}"
            )

        return strategy.create_material_from_textures(
            material_name, texture_paths, options
        )

    def _import_hdri_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import an HDRI composite as an environment light."""
        if composite.composite_type != CompositeType.HDRI:
            raise ValueError(f"Expected HDRI composite, got: {composite.composite_type}")

        renderer = options.get("renderer") or self.get_active_renderer()
        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        selected = self._get_asset_for_resolution(composite, target_resolution)
        if not selected or not selected.local_path:
            raise ValueError(f"No local HDRI available for: {composite.name}")

        if target_resolution:
            found_res = (
                selected.metadata.get("resolution")
                if isinstance(selected.metadata, dict)
                else None
            )
            if found_res != target_resolution:
                logger.warning(
                    f"Requested resolution {target_resolution} but using {found_res or 'unknown'} for HDRI {composite.name}"
                )

        # Pass a narrowed composite (single selected leaf) to the strategy.
        narrowed = CompositeAsset(
            id=composite.id,
            source=composite.source,
            external_id=composite.external_id,
            name=composite.name,
            composite_type=composite.composite_type,
            thumbnail_url=composite.thumbnail_url,
            thumbnail_path=composite.thumbnail_path,
            metadata=composite.metadata.copy() if isinstance(composite.metadata, dict) else {},
            children=[selected],
        )

        return strategy.create_environment_light(narrowed, options)

    def _import_model_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import a MODEL composite as geometry."""
        if composite.composite_type != CompositeType.MODEL:
            raise ValueError(f"Expected MODEL composite, got: {composite.composite_type}")

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        selected = self._get_asset_for_resolution(composite, target_resolution)
        if not selected or not selected.local_path:
            raise ValueError(f"No local model file available for: {composite.name}")

        # Reuse existing model import path by converting to StandardAsset.
        std = StandardAsset(
            id=selected.id,
            source=selected.source,
            external_id=selected.external_id,
            name=composite.name,
            type=AssetType.MODEL,
            status=AssetStatus.LOCAL,
            local_path=selected.local_path,
            thumbnail_url=selected.thumbnail_url or "",
            thumbnail_path=selected.thumbnail_path,
            metadata=selected.metadata.copy() if isinstance(selected.metadata, dict) else {},
        )

        return self._import_model(std, options)

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

    def _find_hdri_file(self, asset: StandardAsset) -> Path | None:
        """Find the HDRI file path for an HDRI asset."""
        if not asset.local_path:
            return None

        if asset.local_path.is_file():
            return asset.local_path

        files = asset.metadata.get("files", {}) if isinstance(asset.metadata, dict) else {}
        rel = files.get("hdri") if isinstance(files, dict) else None
        if isinstance(rel, str) and rel:
            candidate = asset.local_path / rel
            if candidate.exists():
                return candidate

        hdri_extensions = {".hdr", ".exr", ".hdri"}
        if asset.local_path.is_dir():
            for f in asset.local_path.iterdir():
                if f.suffix.lower() in hdri_extensions:
                    return f

        return None

    def _collect_standard_asset_textures(self, asset: StandardAsset) -> dict[str, Path]:
        """
        Collect texture map paths from a legacy StandardAsset.

        Uses `asset.metadata["files"]` and resolves entries relative to `asset.local_path`
        when it is a directory.
        """
        if not asset.local_path:
            raise ValueError(f"Asset {asset.name} has no local path")

        root = asset.local_path if asset.local_path.is_dir() else asset.local_path.parent
        files_any = asset.metadata.get("files", {}) if isinstance(asset.metadata, dict) else {}
        files: dict[str, str] = files_any if isinstance(files_any, dict) else {}

        textures: dict[str, Path] = {}
        for key, rel in files.items():
            if not isinstance(key, str) or not isinstance(rel, str):
                continue
            p = (root / rel).resolve()
            if p.exists():
                textures[key] = p

        if not textures:
            raise ValueError(f"No texture maps found for asset: {asset.name}")

        return textures

    def _guess_material_name_from_texture_composite(self, texture: CompositeAsset) -> str:
        """
        Best-effort material name inference for importing a single TEXTURE composite.

        This is used when a grouped texture has no enclosing MATERIAL composite.
        """
        ext_id = texture.external_id or texture.name

        # Local plugin: "<dir>::<basename>::<map_type>"
        if "::" in ext_id:
            parts = ext_id.split("::")
            if len(parts) >= 3 and parts[-2]:
                return parts[-2]

        # PolyHaven texture composite: "<material_id>:<map_type>"
        if ":" in ext_id:
            left = ext_id.split(":", 1)[0]
            if left:
                return left

        # Fallback: try a local filename stem.
        for child in texture.children:
            if isinstance(child, Asset) and child.local_path:
                return child.local_path.stem

        return texture.name

    def _resolution_key(self, asset: Asset) -> int:
        """Sort key for comparing texture/HDRI/model resolutions."""
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

    def _get_asset_for_resolution(
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
                # If multiple exist, pick the highest "resolution" anyway for stability.
                return max(exact, key=self._resolution_key)

        return max(local_assets, key=self._resolution_key)

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
