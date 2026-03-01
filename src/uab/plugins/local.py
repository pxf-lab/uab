"""Local library plugin for managing downloaded assets.

This plugin provides access to assets that exist locally (downloaded),
regardless of their original source. It queries the database directly and
supports searching and removal.

It also supports importing arbitrary local files into the library via
`add_assets()`. When importing texture map files, the plugin can optionally
group them into `CompositeAsset` trees based on filename patterns:

- `CompositeType.MATERIAL` (only when multiple map types exist)
  - `CompositeType.TEXTURE` per map type (diffuse, normal, etc.)
    - leaf `Asset` children per available resolution
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
import re
import shutil
from pathlib import Path
from string import Formatter
from typing import TYPE_CHECKING, Any

from uab.core.database import AssetDatabase
from uab.core.interfaces import Browsable
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)
from uab.core.thumbnails import propagate_preferred_thumbnail
from uab.plugins.base import SharedAssetLibraryUtils

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_GROUPING_PATTERN = "{basename}_{maptype}_{resolution}.{ext}"


def _stable_id(source: str, external_id: str) -> str:
    """Stable primary key helper for DB upserts (and UI caching)."""
    return f"{source}-{external_id}"


def _resolution_sort_key(value: str | None) -> int:
    """Sort key for resolution strings like '1k', '2k', '4k' (higher is better)."""
    if not value:
        return 0
    m = re.match(r"(?i)^(?P<num>\d+)\s*k$", value.strip())
    if not m:
        return 0
    try:
        return int(m.group("num"))
    except ValueError:
        return 0


@dataclass(frozen=True)
class _GroupedTextureName:
    basename: str
    map_type: str
    resolution: str | None


def _compile_grouping_pattern(pattern: str) -> re.Pattern[str]:
    """
    Compile a grouping pattern into a regex.

    Supported forms:
    - A template string with placeholders: {basename}, {maptype}/{map_type},
      {resolution} (optional), {ext}
    - A raw regex containing named groups (e.g. (?P<basename>...))
    """
    # If the user provides a regex with named groups, use it directly.
    if "(?P<" in pattern:
        return re.compile(pattern, flags=re.IGNORECASE)

    regex_parts: list[str] = []
    for literal_text, field_name, _format_spec, _conversion in Formatter().parse(pattern):
        if field_name is None:
            regex_parts.append(re.escape(literal_text))
            continue

        # Special case: make "separator + {resolution}" optional for common templates.
        if field_name == "resolution":
            if literal_text in {"_", "-", " ", "."}:
                sep = re.escape(literal_text)
                regex_parts.append(
                    rf"(?:{sep}(?P<resolution>\d+[kK]))?"
                )
            else:
                regex_parts.append(re.escape(literal_text))
                regex_parts.append(r"(?P<resolution>\d+[kK])")
            continue

        regex_parts.append(re.escape(literal_text))

        if field_name == "basename":
            # Non-greedy to avoid swallowing maptype/resolution.
            regex_parts.append(r"(?P<basename>.+?)")
            continue

        if field_name in {"maptype", "map_type"}:
            # Require at least one letter to avoid grouping things like "foo_2024.png".
            regex_parts.append(
                # Also require each underscore-separated token to start with a letter,
                # so map types don't accidentally consume trailing resolution tokens
                # like "_2k" when resolution is optional.
                r"(?P<maptype>[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z][A-Za-z0-9]*)*)"
            )
            continue

        if field_name == "ext":
            regex_parts.append(r"(?P<ext>[A-Za-z0-9]+)")
            continue

        raise ValueError(f"Unsupported grouping placeholder: {field_name}")

    return re.compile(r"^" + "".join(regex_parts) + r"$", flags=re.IGNORECASE)


class LocalLibraryPlugin(SharedAssetLibraryUtils):
    """
    Plugin for browsing and managing locally downloaded assets.

    This plugin shows all assets that have been downloaded to the local
    library, regardless of their original source (Poly Haven, etc.).

    Key behaviors:
        - search() queries the database for LOCAL status assets
        - can_download is False (assets are already local)
        - can_remove is True (allows deletion of local assets)
        - download() raises NotImplementedError
    """

    plugin_id = "local"
    display_name = "Local Library"
    description = "Browse and manage locally downloaded assets"

    def __init__(
        self,
        db: AssetDatabase | None = None,
        library_root: Path | None = None,
        *,
        grouping_enabled: bool = True,
        grouping_pattern: str = DEFAULT_GROUPING_PATTERN,
    ) -> None:
        """
        Initialize the local library plugin.

        Args:
            db: Optional database instance
            library_root: Root directory for the local library
        """
        super().__init__(db=db, library_root=library_root)

        self.grouping_enabled = grouping_enabled
        self.grouping_pattern = grouping_pattern
        self._grouping_regex = _compile_grouping_pattern(grouping_pattern)

    async def search(self, query: str) -> list[Browsable]:
        """
        Search locally available items by name.

        This view is primarily the "local library": it returns items that are
        already LOCAL. For assets imported via this plugin (source == "local"),
        texture maps can be grouped into composites based on filename patterns.

        Args:
            query: Search string (empty returns all local assets)

        Returns:
            List of matching local Browsable items (ref interfaces.py)
        """
        q = query.strip().lower()

        all_local_assets = self._db.get_local_assets()

        # Group assets imported via this plugin (source == "local") using filename
        # heuristics. For other sources (e.g. PolyHaven), prefer surfacing any
        # persisted composite roots from the database so downloaded HDRIs/materials
        # appear as a single CompositeAsset locally.
        local_source_assets = [
            a for a in all_local_assets if a.source == self.plugin_id]
        other_source_assets = [
            a for a in all_local_assets if a.source != self.plugin_id]

        grouped_roots: list[Browsable] = []
        grouped_asset_ids: set[str] = set()
        if self.grouping_enabled:
            grouped_roots, grouped_asset_ids = self._group_assets(
                local_source_assets)

        standalone_local_assets = [
            a for a in local_source_assets if a.id not in grouped_asset_ids]

        composite_roots: list[CompositeAsset] = []
        composite_local_asset_ids: set[str] = set()
        try:
            root_ids = self._db.get_root_composite_ids_with_local_descendants()
        except Exception:
            root_ids = []

        for cid in root_ids:
            composite = self._db.get_composite_with_children(cid)
            if not composite:
                continue
            self._sort_hdri_variants_for_display(composite)
            propagate_preferred_thumbnail(composite)
            composite_roots.append(composite)
            for a in composite.get_all_assets():
                if a.status == AssetStatus.LOCAL:
                    composite_local_asset_ids.add(a.id)

        # Avoid duplicating leaf assets that are already represented under a composite root
        standalone_other_assets = [
            a for a in other_source_assets if a.id not in composite_local_asset_ids
        ]

        composite_roots.sort(key=lambda c: c.name.lower())
        items: list[Browsable] = [
            *grouped_roots,
            *standalone_local_assets,
            *composite_roots,
            *standalone_other_assets,
        ]

        if not q:
            return items

        return [item for item in items if self._item_matches_query(item, q)]

    async def download(
        self,
        asset: StandardAsset,
        resolution: str | None = None,
    ) -> StandardAsset:
        """
        Not supported - local assets are already downloaded.

        Args:
            asset: The asset (ignored)
            resolution: Resolution preference (ignored)

        Raises:
            NotImplementedError: Always raised as local assets don't need downloading
        """
        raise NotImplementedError(
            "Local library plugin does not support downloading. "
            "Assets are already local."
        )

    @property
    def can_download(self) -> bool:
        """Local plugin does not support downloads (assets are already local)."""
        return False

    @property
    def can_remove(self) -> bool:
        """Local plugin supports removing assets from the library."""
        return True

    def remove_asset(self, asset: Asset | StandardAsset) -> bool:
        """
        Remove an asset from the local library.

        This deletes the asset files from disk and removes the
        database record.

        Args:
            asset: The asset to remove

        Returns:
            True if the asset was successfully removed
        """
        asset_obj = asset.to_asset() if isinstance(asset, StandardAsset) else asset
        logger.info(f"Removing asset from local library: {asset_obj.name}")

        # Delete local files if they exist
        if asset_obj.local_path and asset_obj.local_path.exists():
            try:
                if asset_obj.local_path.is_dir():
                    shutil.rmtree(asset_obj.local_path)
                    logger.debug(f"Deleted directory: {asset_obj.local_path}")
                else:
                    asset_obj.local_path.unlink()
                    logger.debug(f"Deleted file: {asset_obj.local_path}")
            except OSError as e:
                logger.error(f"Failed to delete asset files: {e}")
                # Continue to remove DB record even if file deletion fails

        # Delete thumbnail if it exists
        if asset_obj.thumbnail_path and asset_obj.thumbnail_path.exists():
            try:
                asset_obj.thumbnail_path.unlink()
                logger.debug(f"Deleted thumbnail: {asset_obj.thumbnail_path}")
            except OSError as e:
                logger.warning(f"Failed to delete thumbnail: {e}")

        # Remove from database
        # TODO: should it remove from db even if the files are not deleted?
        deleted = self._db.remove_asset_by_id(asset_obj.id)
        if deleted:
            logger.info(f"Removed asset {asset_obj.name} from database")
        else:
            logger.warning(f"Asset {asset_obj.name} was not found in database")

        return deleted

    def get_settings_schema(self, asset: object) -> dict | None:
        """
        Local assets don't need import settings.

        Returns:
            None (no settings dialog needed)
        """
        return None

    _EXTENSION_MAP: dict[str, AssetType] = {
        # HDRI formats
        ".hdr": AssetType.HDRI,
        ".exr": AssetType.HDRI,
        # Texture formats
        ".png": AssetType.TEXTURE,
        ".jpg": AssetType.TEXTURE,
        ".jpeg": AssetType.TEXTURE,
        ".tif": AssetType.TEXTURE,
        ".tiff": AssetType.TEXTURE,
        # Model formats
        ".obj": AssetType.MODEL,
        ".fbx": AssetType.MODEL,
        ".gltf": AssetType.MODEL,
        ".glb": AssetType.MODEL,
        ".usd": AssetType.MODEL,
        ".usda": AssetType.MODEL,
        ".usdc": AssetType.MODEL,
    }

    def add_assets(self, paths: Path | list[Path]) -> list[Browsable]:
        """
        Add assets from files or directories (import local files).

        Accepts either a single path or list of paths. Each path can be:
        - A file: Added directly if it has a supported extension
        - A directory: Scanned recursively for supported files

        Texture/HDRI/model files can be grouped into composites when
        `grouping_enabled=True`.

        Args:
            paths: Single path or list of paths (files or directories)

        Returns:
            List of top-level Browsable items that were added (Assets and/or CompositeAssets)
        """
        # Normalize to list
        if isinstance(paths, Path):
            paths = [paths]
        if not paths:
            return []

        supported_extensions = set(self._EXTENSION_MAP.keys())

        files_to_process: list[Path] = []
        for path in paths:
            if not path.exists():
                logger.warning(f"Path does not exist: {path}")
                continue
            if path.is_file():
                files_to_process.append(path)
                continue
            if path.is_dir():
                files_to_process.extend(
                    [p for p in path.rglob("*") if p.is_file()]
                )

        new_assets: list[Asset] = []
        processed_assets: list[Asset] = []
        unsupported_count = 0
        skipped_count = 0

        for file_path in files_to_process:
            suffix = file_path.suffix.lower()
            if suffix not in supported_extensions:
                unsupported_count += 1
                logger.debug(f"Skipping unsupported file: {file_path.name}")
                continue

            external_id = str(file_path.resolve())
            existing = self._db.get_asset_by_external_id(
                self.plugin_id, external_id)
            existed = existing is not None

            asset_type = self._EXTENSION_MAP[suffix]

            metadata: dict[str, Any] = {}
            resolution = self._extract_resolution(file_path.stem)
            if resolution:
                metadata["resolution"] = resolution

            fmt = suffix.lstrip(".")
            if fmt:
                metadata["format"] = fmt

            if asset_type == AssetType.TEXTURE and self.grouping_enabled:
                grouped = self._parse_grouped_texture_name(file_path.name)
                if grouped:
                    metadata["map_type"] = grouped.map_type
                    if grouped.resolution:
                        metadata["resolution"] = grouped.resolution

            asset = Asset(
                id=_stable_id(self.plugin_id, external_id),
                source=self.plugin_id,
                external_id=external_id,
                name=file_path.stem,
                asset_type=asset_type,
                status=AssetStatus.LOCAL,
                local_path=file_path,
                remote_url=None,
                thumbnail_url=None,
                thumbnail_path=None,
                metadata=metadata,
            )

            # Persist (idempotent); stable IDs avoid breaking child links later.
            self._db.upsert_asset(asset)
            processed_assets.append(asset)

            if existed:
                skipped_count += 1
            else:
                new_assets.append(asset)
                logger.debug(f"Added asset: {asset.name} ({asset_type.value})")

        added_items: list[Browsable] = []

        if not new_assets:
            logger.info(
                f"Added 0 assets (skipped {skipped_count} existing, {unsupported_count} unsupported)"
            )
            return []

        # When grouping is enabled, return top-level composites for newly-added grouped
        # items (and standalone Assets for other new files).
        if self.grouping_enabled:
            grouped_roots, grouped_asset_ids = self._group_assets(
                processed_assets)
            # Only return roots that contain at least one newly-added asset.
            new_asset_ids = {a.id for a in new_assets}
            for root in grouped_roots:
                if isinstance(root, CompositeAsset) and self._composite_contains_any_asset_id(root, new_asset_ids):
                    added_items.append(root)

            for asset in new_assets:
                if asset.id not in grouped_asset_ids:
                    added_items.append(asset)
        else:
            added_items.extend(new_assets)

        logger.info(
            f"Added {len(new_assets)} assets "
            f"(returned {len(added_items)} items, skipped {skipped_count} existing, {unsupported_count} unsupported)"
        )

        return added_items

    def _extract_resolution(self, stem: str) -> str | None:
        """Extract a trailing resolution token like '_2k' from a filename stem."""
        tokens = re.split(r"[_\-]+", stem.lower())
        if not tokens:
            return None
        last = tokens[-1].strip()
        return last if re.match(r"^\d+k$", last) else None

    def _split_basename_and_resolution(self, stem: str) -> tuple[str, str | None]:
        """Split a filename stem into (basename, resolution) where resolution is a trailing '2k' token."""
        resolution = self._extract_resolution(stem)
        if not resolution:
            return stem, None

        # preserve original stem casing, strip trailing separator + token
        base = re.sub(r"(?i)[_\-]\d+k$", "", stem).strip()
        return (base or stem), resolution

    def _parse_grouped_texture_name(self, filename: str) -> _GroupedTextureName | None:
        """Parse basename/map_type/resolution from a filename using grouping_pattern."""
        # Prefer matching against full filename (incl. extension), but fall back to stem.
        for candidate in (filename, Path(filename).stem):
            match = self._grouping_regex.match(candidate)
            if not match:
                continue

            basename = (match.groupdict().get("basename") or "").strip()
            map_type = (match.groupdict().get("maptype") or "").strip()
            resolution_raw = match.groupdict().get("resolution")

            if not basename or not map_type:
                return None

            resolution = resolution_raw.lower() if isinstance(resolution_raw, str) else None
            return _GroupedTextureName(
                basename=basename,
                map_type=map_type.lower(),
                resolution=resolution,
            )

        return None

    def _extract_basename(self, filename: str) -> str:
        """Extract grouping basename from a filename (falls back to stem)."""
        parsed = self._parse_grouped_texture_name(filename)
        if parsed:
            return parsed.basename
        return Path(filename).stem

    def _group_hdri_assets(self, assets: list[Asset]) -> tuple[list[CompositeAsset], set[str]]:
        """
        Group HDRI Assets into HDRI composites when multiple variants exist.

        Strategy:
        - group by (directory, basename) where basename strips a trailing resolution token (e.g. '_2k')
        - only create a composite when 2+ HDRI files share the same group key
        """
        by_group: dict[tuple[str, str], list[Asset]] = defaultdict(list)
        for asset in assets:
            if asset.asset_type != AssetType.HDRI:
                continue
            if not asset.local_path or not isinstance(asset.local_path, Path):
                continue

            basename, resolution = self._split_basename_and_resolution(
                asset.local_path.stem)
            fmt = asset.local_path.suffix.lower().lstrip(".")

            if isinstance(asset.metadata, dict):
                if resolution:
                    asset.metadata.setdefault("resolution", resolution)
                if fmt:
                    asset.metadata.setdefault("format", fmt)

            group_dir = str(asset.local_path.parent.resolve())
            by_group[(group_dir, basename)].append(asset)

        roots: list[CompositeAsset] = []
        grouped_asset_ids: set[str] = set()

        for (group_dir, basename), children in by_group.items():
            if len(children) < 2:
                continue

            children_sorted = self._sort_hdri_assets(children)

            composite_external_id = f"{group_dir}::{basename}::hdri"
            roots.append(
                CompositeAsset(
                    id=_stable_id(self.plugin_id, composite_external_id),
                    source=self.plugin_id,
                    external_id=composite_external_id,
                    name=basename,
                    composite_type=CompositeType.HDRI,
                    thumbnail_url=None,
                    thumbnail_path=None,
                    metadata={},
                    children=children_sorted,
                )
            )
            grouped_asset_ids.update(a.id for a in children)

        return roots, grouped_asset_ids

    def _sort_hdri_assets(self, assets: list[Asset]) -> list[Asset]:
        """Sort HDRI variants by resolution desc, then preferred format, then name."""
        format_preference = {"hdr": 0, "exr": 1}

        def _asset_format(asset: Asset) -> str:
            if isinstance(asset.metadata, dict):
                fmt_any = asset.metadata.get("format")
                if isinstance(fmt_any, str) and fmt_any:
                    return fmt_any.lower()
            if asset.local_path:
                suffix = asset.local_path.suffix.lower().lstrip(".")
                if suffix:
                    return suffix
            return ""

        return sorted(
            assets,
            key=lambda a: (
                -_resolution_sort_key(
                    a.metadata.get("resolution") if isinstance(
                        a.metadata, dict) else None
                ),
                format_preference.get(_asset_format(a), 99),
                a.name.lower(),
            ),
        )

    def _sort_hdri_variants_for_display(self, composite: CompositeAsset) -> None:
        """
        Normalize HDRI variant ordering recursively for stable local detail display.

        This applies to composites loaded from DB (including non-local sources).
        """
        if (
            composite.composite_type == CompositeType.HDRI
            and composite.children
            and all(isinstance(c, Asset) for c in composite.children)
        ):
            hdri_assets = [c for c in composite.children if isinstance(c, Asset)]
            composite.children = self._sort_hdri_assets(hdri_assets)
            return

        for child in composite.children:
            if isinstance(child, CompositeAsset):
                self._sort_hdri_variants_for_display(child)

    def _group_model_assets(self, assets: list[Asset]) -> tuple[list[CompositeAsset], set[str]]:
        """
        Group model Assets into MODEL composites when multiple variants exist.

        Strategy:
        - group by (directory, basename) where basename strips a trailing resolution token (e.g. '_2k')
        - only create a composite when 2+ model files share the same group key
        """
        by_group: dict[tuple[str, str], list[Asset]] = defaultdict(list)
        for asset in assets:
            if asset.asset_type != AssetType.MODEL:
                continue
            if not asset.local_path or not isinstance(asset.local_path, Path):
                continue

            basename, resolution = self._split_basename_and_resolution(
                asset.local_path.stem)
            fmt = asset.local_path.suffix.lower().lstrip(".")

            if isinstance(asset.metadata, dict):
                if resolution:
                    asset.metadata.setdefault("resolution", resolution)
                if fmt:
                    asset.metadata.setdefault("format", fmt)

            group_dir = str(asset.local_path.parent.resolve())
            by_group[(group_dir, basename)].append(asset)

        # Prefer more "scene-friendly" formats first (ties only).
        format_preference = {
            "usd": 0,
            "usda": 0,
            "usdc": 0,
            "glb": 1,
            "gltf": 1,
            "fbx": 2,
            "obj": 3,
        }

        roots: list[CompositeAsset] = []
        grouped_asset_ids: set[str] = set()

        for (group_dir, basename), children in by_group.items():
            if len(children) < 2:
                continue

            children_sorted = sorted(
                children,
                key=lambda a: (
                    -_resolution_sort_key(
                        a.metadata.get("resolution") if isinstance(
                            a.metadata, dict) else None
                    ),
                    format_preference.get(
                        (a.metadata.get("format") if isinstance(
                            a.metadata, dict) else None) or "", 99
                    ),
                    a.name.lower(),
                ),
            )

            composite_external_id = f"{group_dir}::{basename}::model"
            roots.append(
                CompositeAsset(
                    id=_stable_id(self.plugin_id, composite_external_id),
                    source=self.plugin_id,
                    external_id=composite_external_id,
                    name=basename,
                    composite_type=CompositeType.MODEL,
                    thumbnail_url=None,
                    thumbnail_path=None,
                    metadata={},
                    children=children_sorted,
                )
            )
            grouped_asset_ids.update(a.id for a in children)

        return roots, grouped_asset_ids

    def _group_assets(self, assets: list[Asset]) -> tuple[list[Browsable], set[str]]:
        """Group local Assets into appropriate composite trees."""
        roots: list[Browsable] = []
        grouped_asset_ids: set[str] = set()

        tex_roots, tex_ids = self._group_texture_assets(assets)
        roots.extend(tex_roots)
        grouped_asset_ids.update(tex_ids)

        hdri_roots, hdri_ids = self._group_hdri_assets(assets)
        roots.extend(hdri_roots)
        grouped_asset_ids.update(hdri_ids)

        model_roots, model_ids = self._group_model_assets(assets)
        roots.extend(model_roots)
        grouped_asset_ids.update(model_ids)

        return roots, grouped_asset_ids

    def _group_texture_assets(self, assets: list[Asset]) -> tuple[list[Browsable], set[str]]:
        """
        Group texture-map Assets into MATERIAL/TEXTURE composites.

        Returns:
            (root_items, grouped_asset_ids)
        """
        # Group only local TEXTURE assets with a parseable filename.
        by_group: dict[tuple[str, str], dict[str, list[Asset]]] = defaultdict(
            lambda: defaultdict(list)
        )
        grouped_asset_ids: set[str] = set()

        for asset in assets:
            if asset.asset_type != AssetType.TEXTURE:
                continue
            if not asset.local_path or not isinstance(asset.local_path, Path):
                continue

            parsed = self._parse_grouped_texture_name(asset.local_path.name)
            if not parsed:
                continue

            group_dir = str(asset.local_path.parent.resolve())
            group_key = (group_dir, parsed.basename)
            by_group[group_key][parsed.map_type].append(asset)
            grouped_asset_ids.add(asset.id)

            # Keep metadata in sync for later import steps.
            if isinstance(asset.metadata, dict):
                asset.metadata.setdefault("map_type", parsed.map_type)
                if parsed.resolution:
                    asset.metadata.setdefault("resolution", parsed.resolution)

        roots: list[Browsable] = []

        for (group_dir, basename), map_groups in by_group.items():
            map_types = sorted(map_groups.keys())
            texture_composites: list[CompositeAsset] = []

            has_multiple_maps = len(map_types) > 1

            for map_type in map_types:
                children = map_groups[map_type]
                # Sort by resolution descending (highest first), then by name for stability.
                children_sorted = sorted(
                    children,
                    key=lambda a: (
                        -_resolution_sort_key(
                            a.metadata.get("resolution") if isinstance(
                                a.metadata, dict) else None
                        ),
                        a.name.lower(),
                    ),
                )

                texture_external_id = f"{group_dir}::{basename}::{map_type}"
                texture_meta: dict[str, Any] = {"map_type": map_type}
                if has_multiple_maps:
                    texture_meta["role"] = map_type

                texture_composites.append(
                    CompositeAsset(
                        id=_stable_id(self.plugin_id, texture_external_id),
                        source=self.plugin_id,
                        external_id=texture_external_id,
                        name=map_type,
                        composite_type=CompositeType.TEXTURE,
                        thumbnail_url=None,
                        thumbnail_path=None,
                        metadata=texture_meta,
                        children=children_sorted,
                    )
                )

            if has_multiple_maps:
                material_external_id = f"{group_dir}::{basename}"
                roots.append(
                    CompositeAsset(
                        id=_stable_id(self.plugin_id, material_external_id),
                        source=self.plugin_id,
                        external_id=material_external_id,
                        name=basename,
                        composite_type=CompositeType.MATERIAL,
                        thumbnail_url=None,
                        thumbnail_path=None,
                        metadata={},
                        children=texture_composites,
                    )
                )
            else:
                roots.extend(texture_composites)

        return roots, grouped_asset_ids

    def _item_matches_query(self, item: Browsable, q: str) -> bool:
        """Return True if item or any descendant name matches the query."""
        if q in item.name.lower():
            return True
        if isinstance(item, CompositeAsset):
            for child in item.children:
                # child is Asset or CompositeAsset
                if q in child.name.lower():
                    return True
                if isinstance(child, CompositeAsset) and self._item_matches_query(child, q):
                    return True
        return False

    def _prune_composite_to_local(self, composite: CompositeAsset) -> CompositeAsset | None:
        """
        Return `composite` pruned to LOCAL descendant Assets only.

        Any composite nodes that end up empty after pruning are removed.
        """

        def _prune(node: Browsable) -> Browsable | None:
            if isinstance(node, Asset):
                return node if node.status == AssetStatus.LOCAL else None

            if isinstance(node, CompositeAsset):
                kept: list[Browsable] = []
                for child in node.children:
                    pruned_child = _prune(child)
                    if pruned_child is not None:
                        kept.append(pruned_child)
                if not kept:
                    return None
                node.children = kept
                return node

            return None

        pruned = _prune(composite)
        return pruned if isinstance(pruned, CompositeAsset) else None

    def _composite_contains_any_asset_id(self, composite: CompositeAsset, asset_ids: set[str]) -> bool:
        """Return True if any descendant Asset has an ID in asset_ids."""
        for child in composite.children:
            if isinstance(child, Asset):
                if child.id in asset_ids:
                    return True
                continue
            if isinstance(child, CompositeAsset):
                if self._composite_contains_any_asset_id(child, asset_ids):
                    return True
        return False
