"""Maya host integration for Universal Asset Browser.

This module intentionally avoids importing Maya modules at import time so the
package can be imported outside of Maya (e.g. unit tests, standalone mode).
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from uab.core.interfaces import HostIntegration, RenderStrategy
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)
from uab.integrations.maya._maya import require_cmds

logger = logging.getLogger(__name__)


class MayaIntegration(HostIntegration):
    """Maya-specific host integration (Maya 2025+ / PySide6)."""

    _SUPPORTED_RENDERERS = ["arnold", "redshift"]

    # Common plugin name candidates (varies by installation)
    # TODO: need a more robust way to detect the plugins
    _ARNOLD_PLUGIN_CANDIDATES = ("mtoa",)
    _REDSHIFT_PLUGIN_CANDIDATES = (
        "redshift4maya",
        "redshift4maya.mll",
        "redshift",
    )
    _FBX_PLUGIN_CANDIDATES = ("fbxmaya", "fbxmaya.mll")
    _ALEMBIC_PLUGIN_CANDIDATES = ("AbcImport", "AbcImport.mll")
    _USD_PLUGIN_CANDIDATES = (
        "mayaUsdPlugin",
        "mayaUsdPlugin.mll",
    )

    def __init__(self) -> None:
        self._strategies: dict[str, RenderStrategy] = {}
        self._load_strategies()

    def _load_strategies(self) -> None:
        """Load renderer strategies (best-effort; may be unavailable outside Maya)."""
        strategies: dict[str, RenderStrategy] = {}

        try:
            from uab.integrations.maya.strategies.arnold import ArnoldStrategy

            strategies["arnold"] = ArnoldStrategy()
        except Exception as e:
            logger.debug(f"Arnold strategy not available: {e}")

        self._strategies = strategies

    @property
    def uab_supported_renderers(self) -> list[str]:
        # A renderer is considered supported when it has a registered strategy.
        return [r for r in self._SUPPORTED_RENDERERS if r in self._strategies]

    # MAYA HELPERS

    def _maya_cmds(self):
        return require_cmds()

    def _plugin_available(self, plugin_name: str) -> bool:
        """Return True if a plugin is available (installed) in this Maya."""
        cmds = self._maya_cmds()
        try:
            return bool(cmds.pluginInfo(plugin_name, query=True, available=True))
        except Exception:
            return False

    def _plugin_loaded(self, plugin_name: str) -> bool:
        cmds = self._maya_cmds()
        try:
            return bool(cmds.pluginInfo(plugin_name, query=True, loaded=True))
        except Exception:
            return False

    def _ensure_plugin_loaded(self, plugin_name: str) -> bool:
        """Best-effort load. Returns True when loaded/usable."""
        cmds = self._maya_cmds()
        if self._plugin_loaded(plugin_name):
            return True
        try:
            if self._plugin_available(plugin_name):
                cmds.loadPlugin(plugin_name)
                return self._plugin_loaded(plugin_name)
        except Exception as e:
            logger.debug(f"Failed to load plugin '{plugin_name}': {e}")
        return False

    def _ensure_any_plugin_loaded(self, candidates: tuple[str, ...]) -> str | None:
        """Try to load one plugin from candidates and return its name if loaded."""
        for plugin in candidates:
            if self._ensure_plugin_loaded(plugin) or self._plugin_loaded(plugin):
                return plugin
        return None

    @contextmanager
    def _undo_chunk(self, name: str):
        """Context manager that groups operations into one Maya undo step."""
        try:
            cmds = self._maya_cmds()
        except Exception:
            # Outside Maya
            yield
            return

        try:
            cmds.undoInfo(openChunk=True, chunkName=name)
            yield
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                # Avoid masking original errors
                pass

    # RENDERER DETECTION

    def get_host_available_renderers(self) -> list[str]:
        """Return renderers that are available in Maya (installed/usable)."""
        available: list[str] = []

        # Arnold (mtoa)
        for plugin in self._ARNOLD_PLUGIN_CANDIDATES:
            if self._plugin_loaded(plugin) or self._plugin_available(plugin):
                available.append("arnold")
                break

        # Redshift
        for plugin in self._REDSHIFT_PLUGIN_CANDIDATES:
            if self._plugin_loaded(plugin) or self._plugin_available(plugin):
                available.append("redshift")
                break

        return available

    def get_active_renderer(self) -> str:
        """Return active renderer identifier."""
        try:
            cmds = self._maya_cmds()
            current = cmds.getAttr("defaultRenderGlobals.currentRenderer")
        except Exception:
            # Outside Maya or missing node: fall back
            current = None

        if isinstance(current, str):
            value = current.strip().lower()
            if value in ("arnold", "mtoa"):
                return "arnold"
            if value in ("redshift", "rs"):
                return "redshift"

        # Fall back to first supported available
        available = self.get_host_available_renderers()
        for r in self._SUPPORTED_RENDERERS:
            if r in available:
                return r

        # Ultimate fallback (UI expects some renderer string)
        return "arnold"

    def _get_strategy(self, renderer: str | None = None) -> RenderStrategy | None:
        if renderer is None:
            renderer = self.get_active_renderer()

        strategy = self._strategies.get(renderer)
        if strategy is None:
            logger.warning(f"No strategy available for renderer: {renderer}")
        return strategy

    # HOST UI AFFORDANCES

    @property
    def supports_replace_selection(self) -> bool:
        return False

    def get_node_label_for_asset_type(self, asset_type: AssetType) -> str:
        labels = {
            AssetType.HDRI: "Skydome Light",
            AssetType.TEXTURE: "Material",
            AssetType.MODEL: "Geometry",
        }
        return labels.get(asset_type, asset_type.value.title())

    # IMPORT API

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        """Import a legacy StandardAsset into Maya."""
        renderer = options.get("renderer") or self.get_active_renderer()
        strategy = self._get_strategy(renderer)
        if strategy is None:
            raise ValueError(f"No import strategy for renderer: {renderer}")

        with self._undo_chunk(f"UAB Import: {asset.name}"):
            if asset.type == AssetType.HDRI:
                self._import_hdri_leaf(asset, strategy, options)
                return
            if asset.type == AssetType.TEXTURE:
                textures = self._collect_standard_asset_textures(asset)
                strategy.create_material_from_textures(
                    asset.name, textures, options)
                return
            if asset.type == AssetType.MODEL:
                self._import_model(asset, options)
                return

            raise ValueError(f"Unsupported asset type: {asset.type}")

    def import_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import a composite into Maya (wrapped in an undo chunk when possible)."""
        with self._undo_chunk(f"UAB Import: {composite.name}"):
            return super().import_composite(composite, options)

    def _import_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """
        Import a MATERIAL or TEXTURE composite as a Maya material.

        Traverses texture children, picks the best LOCAL variant for the requested
        resolution, then delegates to the active renderer strategy.
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
            material_name = self._guess_material_name_from_texture_composite(
                composite)
            texture_nodes = [composite]

        texture_paths: dict[str, Path] = {}
        missing_maps: set[str] = set()
        resolution_mismatches: dict[str, str | None] = {}

        for child in texture_nodes:
            role: str | None = None
            if isinstance(child.metadata, dict):
                role_any = child.metadata.get(
                    "role") or child.metadata.get("map_type")
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

        required_variants = strategy.get_required_texture_maps()
        if required_variants and not any(k in texture_paths for k in required_variants):
            pretty = "/".join(sorted(required_variants))
            raise ValueError(
                f"Missing required texture map (any of): {pretty}. "
                f"Available: {', '.join(sorted(texture_paths.keys())) or '(none)'}"
            )

        optional = strategy.get_optional_texture_maps()
        missing_optional = sorted(
            {k for k in optional if k not in texture_paths})
        if missing_optional:
            logger.info(
                f"Missing optional textures for {material_name}: {', '.join(missing_optional)}"
            )

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

        return strategy.create_material_from_textures(material_name, texture_paths, options)

    def _import_hdri_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import an HDRI composite as an environment light."""
        if composite.composite_type != CompositeType.HDRI:
            raise ValueError(
                f"Expected HDRI composite, got: {composite.composite_type}")

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

        # Pass a narrowed composite (single selected leaf) to the strategy.
        narrowed = CompositeAsset(
            id=composite.id,
            source=composite.source,
            external_id=composite.external_id,
            name=composite.name,
            composite_type=composite.composite_type,
            thumbnail_url=composite.thumbnail_url,
            thumbnail_path=composite.thumbnail_path,
            metadata=composite.metadata.copy() if isinstance(
                composite.metadata, dict) else {},
            children=[selected],
        )

        return strategy.create_environment_light(narrowed, options)

    def _import_model_composite(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:
        """Import a MODEL composite as geometry."""
        if composite.composite_type != CompositeType.MODEL:
            raise ValueError(
                f"Expected MODEL composite, got: {composite.composite_type}")

        target_resolution = options.get("resolution")
        if not isinstance(target_resolution, str):
            target_resolution = None

        selected = self._get_asset_for_resolution(composite, target_resolution)
        if not selected or not selected.local_path:
            raise ValueError(
                f"No local model file available for: {composite.name}")

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

    def update_selection(self, asset: StandardAsset) -> None:
        """Selection replacement is intentionally disabled for initial Maya port."""
        logger.info(
            f"Maya replace selection not supported (requested: {asset.name})")
        return None

    # LEAF IMPORT HELPERS

    def _import_hdri_leaf(
        self, asset: StandardAsset, strategy: RenderStrategy, options: dict[str, Any]
    ) -> Any:
        hdri_path = self._find_hdri_file(asset)
        if not hdri_path:
            raise ValueError(f"No HDRI file found for asset: {asset.name}")

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

        return strategy.create_environment_light(composite, options)

    def _import_model(self, asset: StandardAsset, options: dict[str, Any]) -> Any:
        if not asset.local_path:
            raise ValueError(f"Asset {asset.name} has no local path")

        model_path = self._find_geometry_file(asset)
        if not model_path:
            raise ValueError(f"No geometry file found for asset: {asset.name}")

        return self._import_model_file(Path(model_path), options=options)

    def _import_model_file(self, path: Path, options: dict[str, Any]) -> Any:
        """Import a model file into Maya, routing by extension when possible."""
        cmds = self._maya_cmds()
        if not path.exists():
            raise ValueError(f"Model path does not exist: {path}")

        ext = path.suffix.lower()

        # FBX
        if ext == ".fbx":
            loaded = self._ensure_any_plugin_loaded(
                self._FBX_PLUGIN_CANDIDATES)
            if not loaded:
                raise ValueError(
                    "FBX import requires the 'fbxmaya' plugin (not available/loaded)."
                )
            # Let Maya pick the importer; plugin load usually registers it.
            return cmds.file(
                str(path),
                i=True,
                ignoreVersion=True,
                mergeNamespacesOnClash=False,
                prompt=False,
            )

        # Alembic
        if ext == ".abc":
            loaded = self._ensure_any_plugin_loaded(
                self._ALEMBIC_PLUGIN_CANDIDATES)
            if not loaded:
                raise ValueError(
                    "Alembic import requires the 'AbcImport' plugin (not available/loaded)."
                )
            abc_import = getattr(cmds, "AbcImport", None)
            if not callable(abc_import):
                raise ValueError(
                    "Alembic import command 'AbcImport' is not available.")
            # Returns None; import happens as a side effect.
            return abc_import(str(path), mode="import")

        # USD (MayaUSD)
        if ext in (".usd", ".usda", ".usdc"):
            loaded = self._ensure_any_plugin_loaded(
                self._USD_PLUGIN_CANDIDATES)
            if not loaded:
                raise ValueError(
                    "USD import requires MayaUSD ('mayaUsdPlugin') to be installed."
                )
            # Prefer explicit type if the importer is registered; fall back to generic.
            try:
                return cmds.file(
                    str(path),
                    i=True,
                    type="USD Import",
                    ignoreVersion=True,
                    mergeNamespacesOnClash=False,
                    prompt=False,
                )
            except Exception:
                return cmds.file(
                    str(path),
                    i=True,
                    ignoreVersion=True,
                    mergeNamespacesOnClash=False,
                    prompt=False,
                )

        # Generic fallbacks (.obj, .gltf, .glb, etc.)
        return cmds.file(
            str(path),
            i=True,
            ignoreVersion=True,
            mergeNamespacesOnClash=False,
            prompt=False,
        )

    # LEGACY STANDARDASSET HELPERS

    def _find_geometry_file(self, asset: StandardAsset) -> str | None:
        if not asset.local_path:
            return None

        files_any = asset.metadata.get("files", {}) if isinstance(
            asset.metadata, dict) else {}
        files: dict[str, str] = files_any if isinstance(
            files_any, dict) else {}

        if "geometry" in files:
            return str(asset.local_path / files["geometry"])
        if "model" in files:
            return str(asset.local_path / files["model"])

        if asset.local_path.is_file():
            return str(asset.local_path)

        geo_extensions = [
            ".obj",
            ".fbx",
            ".abc",
            ".usd",
            ".usda",
            ".usdc",
            ".gltf",
            ".glb",
        ]
        if asset.local_path.is_dir():
            for f in asset.local_path.iterdir():
                if f.suffix.lower() in geo_extensions:
                    return str(f)
        return None

    def _find_hdri_file(self, asset: StandardAsset) -> Path | None:
        if not asset.local_path:
            return None

        if asset.local_path.is_file():
            return asset.local_path

        files = asset.metadata.get("files", {}) if isinstance(
            asset.metadata, dict) else {}
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
        if not asset.local_path:
            raise ValueError(f"Asset {asset.name} has no local path")

        root = asset.local_path if asset.local_path.is_dir() else asset.local_path.parent
        files_any = asset.metadata.get("files", {}) if isinstance(
            asset.metadata, dict) else {}
        files: dict[str, str] = files_any if isinstance(
            files_any, dict) else {}

        textures: dict[str, Path] = {}
        for key, rel in files.items():
            if not isinstance(key, str) or not isinstance(rel, str):
                continue
            p = (root / rel).resolve()
            if p.exists():
                textures[key] = p

        if not textures:
            # Fall back to single-file assets (treat the path as the map)
            if asset.local_path and asset.local_path.is_file():
                textures["diffuse"] = asset.local_path
            else:
                raise ValueError(
                    f"No texture maps found for asset: {asset.name}")

        return textures

    def _guess_material_name_from_texture_composite(self, texture: CompositeAsset) -> str:
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

        for child in texture.children:
            if isinstance(child, Asset) and child.local_path:
                return child.local_path.stem

        return texture.name

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

    def _get_asset_for_resolution(
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
