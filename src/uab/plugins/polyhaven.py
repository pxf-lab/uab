"""PolyHaven plugin for cloud asset integration.

PolyHaven supports three major asset categories. This plugin represents them
as `CompositeAsset` trees:

- Materials (`t=textures`): `CompositeType.MATERIAL` (search result)
  - `CompositeType.TEXTURE` children for each map type (diffuse, normal, etc.)
    - leaf `Asset` children per available resolution (1k, 2k, 4k, 8k)
- HDRIs (`t=hdris`): `CompositeType.HDRI` (search result)
  - leaf `Asset` children per available resolution (preferring `.hdr`)
- Models (`t=models`): `CompositeType.MODEL` (search result)
  - leaf `Asset` children for available file formats/resolutions

API Documentation: https://github.com/Poly-Haven/Public-API
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from uab.core.database import AssetDatabase
from uab.core.interfaces import Browsable
from uab.core.models import Asset, AssetStatus, AssetType, CompositeAsset, CompositeType
from uab.plugins.base import SharedAssetLibraryUtils

logger = logging.getLogger(__name__)

# PolyHaven API endpoints
API_BASE = "https://api.polyhaven.com"
API_ASSETS = f"{API_BASE}/assets"  # ?t=hdris, ?t=textures, ?t=models
API_INFO = f"{API_BASE}/info"  # /{id}
API_FILES = f"{API_BASE}/files"  # /{id}

AVAILABLE_RESOLUTIONS = ["1k", "2k", "4k", "8k"]
DEFAULT_RESOLUTION = "2k"  # TODO: make this configurable

# prefer a single file per resolution
_PREFERRED_TEXTURE_FORMATS = ["png", "jpg", "exr", "tif", "tiff"]
_PREFERRED_HDRI_FORMATS = ["hdr", "exr"]
_MODEL_FORMAT_ORDER = ["gltf", "fbx", "blend", "usd"]

# deterministic, ui-friendly ordering, only keys that exist in a manifest are used
_MAP_TYPE_ORDER = [
    "diffuse",
    "diff",
    "albedo",
    "basecolor",
    "normal",
    "nor_gl",
    "nor_dx",
    "roughness",
    "rough",
    "displacement",
    "disp",
    "arm",
    "ao",
    "metallic",
    "metal",
]


def _stable_id(source: str, external_id: str) -> str:
    """Stable primary key helper for DB upserts."""
    return f"{source}-{external_id}"


def _safe_lower(value: Any) -> str:
    return str(value).lower() if value is not None else ""


class PolyHavenPlugin(SharedAssetLibraryUtils):
    """Plugin for browsing and downloading PolyHaven assets."""

    plugin_id = "polyhaven"
    display_name = "PolyHaven"
    description = "Free CC0 HDRIs, materials, and models from PolyHaven"

    def __init__(
        self,
        db: AssetDatabase | None = None,
        library_root: Path | None = None,
        asset_type_filter: AssetType | None = None,
    ) -> None:
        super().__init__(db=db, library_root=library_root)
        self._asset_type_filter = asset_type_filter

    async def search(self, query: str) -> list[Browsable]:
        """Search PolyHaven assets and return top-level composites."""
        type_specs: list[tuple[AssetType, str, CompositeType]] = [
            (AssetType.HDRI, "hdris", CompositeType.HDRI),
            (AssetType.TEXTURE, "textures", CompositeType.MATERIAL),
            (AssetType.MODEL, "models", CompositeType.MODEL),
        ]

        if self._asset_type_filter is not None:
            type_specs = [spec for spec in type_specs if spec[0]
                          == self._asset_type_filter]

        q = query.strip().lower()
        results: list[CompositeAsset] = []

        for asset_type, api_type, composite_type in type_specs:
            url = f"{API_ASSETS}?t={api_type}"
            try:
                data = await self._fetch_json(url)
            except Exception as e:
                logger.error(f"Failed to fetch {api_type} from PolyHaven: {e}")
                continue

            if not isinstance(data, dict):
                logger.warning(f"Unexpected response from {url}: {type(data)}")
                continue

            for external_id, info_any in data.items():
                info = info_any if isinstance(info_any, dict) else {}
                name = info.get("name", external_id)

                if q and q not in _safe_lower(name):
                    continue

                thumbnail_url = info.get("thumbnail_url")
                if not thumbnail_url:
                    thumbnail_url = (
                        f"https://cdn.polyhaven.com/asset_img/thumbs/{external_id}.png?height=256"
                    )

                composite = CompositeAsset(
                    id=_stable_id(self.plugin_id, external_id),
                    source=self.plugin_id,
                    external_id=external_id,
                    name=name,
                    composite_type=composite_type,
                    thumbnail_url=thumbnail_url,
                    thumbnail_path=None,
                    metadata={
                        "asset_type": asset_type.value,
                        "license": "CC0",
                        "categories": info.get("categories", []),
                        "tags": info.get("tags", []),
                        "authors": info.get("authors", {}),
                        "date_published": info.get("date_published"),
                    },
                    children=[],
                )
                composite.thumbnail_path = self.get_thumbnail_cache_path(
                    composite)
                results.append(composite)

        return results

    async def expand_composite(self, composite: CompositeAsset) -> CompositeAsset:
        """Expand a composite item (lazy load/populate its children)."""
        if composite.source != self.plugin_id:
            raise ValueError(
                f"Composite is not from PolyHaven: {composite.source}")

        if composite.composite_type == CompositeType.MATERIAL:
            return await self._expand_material(composite)

        if composite.composite_type == CompositeType.TEXTURE:
            return await self._expand_texture(composite)

        if composite.composite_type == CompositeType.HDRI:
            return await self._expand_hdri(composite)

        if composite.composite_type == CompositeType.MODEL:
            return await self._expand_model(composite)

        # unknown composite type (should never happen)
        return composite

    async def _expand_material(self, material: CompositeAsset) -> CompositeAsset:
        files_url = f"{API_FILES}/{material.external_id}"
        manifest = await self._fetch_json(files_url)

        if not isinstance(manifest, dict):
            logger.warning(
                f"Unexpected response from {files_url}: {type(manifest)}")
            return material

        map_types = [m for m in _MAP_TYPE_ORDER if m in manifest]
        if not map_types:
            # fallback: take any top-level dict-like key as a map type
            map_types = [k for k, v in manifest.items() if isinstance(v, dict)]

        children: list[CompositeAsset] = []
        for map_type in map_types:
            texture_external_id = f"{material.external_id}:{map_type}"
            child = CompositeAsset(
                id=_stable_id(self.plugin_id, texture_external_id),
                source=self.plugin_id,
                external_id=texture_external_id,
                name=map_type,
                composite_type=CompositeType.TEXTURE,
                thumbnail_url=None,
                thumbnail_path=None,
                metadata={
                    "role": map_type,
                    "map_type": map_type,
                },
                children=[],
            )
            children.append(child)

        # persist the composite structure (lazily texture children have no assets yet)
        self._db.upsert_composite(material)
        self._db.set_composite_children(material.id, children)

        material.children = children
        return material

    async def _expand_texture(self, texture: CompositeAsset) -> CompositeAsset:
        # parse `material_id` + `map_type` from "material_id:map_type"
        if ":" in texture.external_id:
            material_id, map_type = texture.external_id.split(":", 1)
        else:
            # avoid crashing on malformed IDs
            material_id, map_type = texture.external_id, texture.name

        files_url = f"{API_FILES}/{material_id}"
        manifest = await self._fetch_json(files_url)
        if not isinstance(manifest, dict):
            logger.warning(
                f"Unexpected response from {files_url}: {type(manifest)}")
            return texture

        map_data = manifest.get(map_type)
        if not isinstance(map_data, dict):
            return texture

        children: list[Asset] = []

        for resolution in AVAILABLE_RESOLUTIONS:
            res_data = map_data.get(resolution)
            if not isinstance(res_data, dict):
                continue

            remote_url: str | None = None
            file_size: int | None = None

            for fmt in _PREFERRED_TEXTURE_FORMATS:
                fmt_data = res_data.get(fmt)
                if isinstance(fmt_data, dict):
                    remote_url = fmt_data.get("url")
                    size_any = fmt_data.get(
                        "size") or fmt_data.get("file_size")
                    if isinstance(size_any, int):
                        file_size = size_any
                    break

            if not remote_url:
                # fallback: first format-like entry with a URL
                for fmt_data in res_data.values():
                    if isinstance(fmt_data, dict) and fmt_data.get("url"):
                        remote_url = fmt_data.get("url")
                        size_any = fmt_data.get(
                            "size") or fmt_data.get("file_size")
                        if isinstance(size_any, int):
                            file_size = size_any
                        break

            if not remote_url:
                continue

            asset_external_id = f"{material_id}:{map_type}:{resolution}"
            filename = Path(remote_url.split("?", 1)[
                            0]).name or asset_external_id

            child = Asset(
                id=_stable_id(self.plugin_id, asset_external_id),
                source=self.plugin_id,
                external_id=asset_external_id,
                name=filename,
                asset_type=AssetType.TEXTURE,
                status=AssetStatus.CLOUD,
                local_path=None,
                remote_url=remote_url,
                thumbnail_url=None,
                thumbnail_path=None,
                file_size=file_size,
                metadata={"resolution": resolution, "map_type": map_type},
            )
            children.append(child)

        # persist assets and link under this texture composite
        self._db.upsert_composite(texture)
        self._db.set_composite_children(texture.id, children)

        texture.children = children
        return texture

    async def _expand_hdri(self, hdri: CompositeAsset) -> CompositeAsset:
        files_url = f"{API_FILES}/{hdri.external_id}"
        manifest = await self._fetch_json(files_url)
        if not isinstance(manifest, dict):
            logger.warning(
                f"Unexpected response from {files_url}: {type(manifest)}")
            return hdri

        hdri_data = manifest.get("hdri")
        if not isinstance(hdri_data, dict):
            return hdri

        children: list[Asset] = []
        for resolution in AVAILABLE_RESOLUTIONS:
            res_data = hdri_data.get(resolution)
            if not isinstance(res_data, dict):
                continue

            remote_url: str | None = None
            file_size: int | None = None
            chosen_fmt: str | None = None

            for fmt in _PREFERRED_HDRI_FORMATS:
                fmt_data = res_data.get(fmt)
                if isinstance(fmt_data, dict) and fmt_data.get("url"):
                    chosen_fmt = fmt
                    remote_url = fmt_data.get("url")
                    size_any = fmt_data.get(
                        "size") or fmt_data.get("file_size")
                    if isinstance(size_any, int):
                        file_size = size_any
                    break

            if not remote_url:
                for fmt, fmt_data in res_data.items():
                    if isinstance(fmt_data, dict) and fmt_data.get("url"):
                        chosen_fmt = str(fmt)
                        remote_url = fmt_data.get("url")
                        size_any = fmt_data.get(
                            "size") or fmt_data.get("file_size")
                        if isinstance(size_any, int):
                            file_size = size_any
                        break

            if not remote_url or not chosen_fmt:
                continue

            asset_external_id = f"{hdri.external_id}:{resolution}:{chosen_fmt}"
            filename = Path(remote_url.split("?", 1)[
                            0]).name or asset_external_id
            child = Asset(
                id=_stable_id(self.plugin_id, asset_external_id),
                source=self.plugin_id,
                external_id=asset_external_id,
                name=filename,
                asset_type=AssetType.HDRI,
                status=AssetStatus.CLOUD,
                local_path=None,
                remote_url=remote_url,
                # propagate to all resolution/format variants
                thumbnail_url=hdri.thumbnail_url,
                thumbnail_path=hdri.thumbnail_path,
                file_size=file_size,
                metadata={"role": resolution,
                          "resolution": resolution, "format": chosen_fmt},
            )
            children.append(child)

        self._db.upsert_composite(hdri)
        self._db.set_composite_children(hdri.id, children)

        hdri.children = children
        return hdri

    async def _expand_model(self, model: CompositeAsset) -> CompositeAsset:
        files_url = f"{API_FILES}/{model.external_id}"
        manifest = await self._fetch_json(files_url)
        if not isinstance(manifest, dict):
            logger.warning(
                f"Unexpected response from {files_url}: {type(manifest)}")
            return model

        children: list[Asset] = []

        for fmt in _MODEL_FORMAT_ORDER:
            fmt_data = manifest.get(fmt)
            if not isinstance(fmt_data, dict):
                continue

            # per polyhaven docs
            resolutions: list[str] = [
                r for r in AVAILABLE_RESOLUTIONS if r in fmt_data]
            resolutions.extend(
                sorted(k for k in fmt_data.keys() if k not in resolutions))

            for resolution in resolutions:
                res_wrapper = fmt_data.get(resolution)
                if not isinstance(res_wrapper, dict):
                    continue

                file_data = res_wrapper.get(fmt)
                if not isinstance(file_data, dict):
                    continue

                remote_url = file_data.get("url")
                if not remote_url:
                    continue

                size_any = file_data.get("size")
                file_size = size_any if isinstance(size_any, int) else None

                asset_external_id = f"{model.external_id}:{fmt}:{resolution}"
                filename = Path(remote_url.split("?", 1)[
                                0]).name or asset_external_id
                children.append(
                    Asset(
                        id=_stable_id(self.plugin_id, asset_external_id),
                        source=self.plugin_id,
                        external_id=asset_external_id,
                        name=filename,
                        asset_type=AssetType.MODEL,
                        status=AssetStatus.CLOUD,
                        local_path=None,
                        remote_url=remote_url,
                        # propagate to all resolution/format variants
                        thumbnail_url=model.thumbnail_url,
                        thumbnail_path=model.thumbnail_path,
                        file_size=file_size,
                        metadata={"format": fmt, "resolution": resolution},
                    )
                )

        self._db.upsert_composite(model)
        self._db.set_composite_children(model.id, children)

        model.children = children
        return model

    async def download_asset(self, asset: Asset) -> Asset:
        """Download a single file Asset from its `remote_url`."""
        if asset.source != self.plugin_id:
            raise ValueError(f"Asset is not from PolyHaven: {asset.source}")
        if not asset.remote_url:
            raise ValueError("Asset has no remote_url to download")

        # external_id is prefixed with a root asset ID (material/hdri/model)
        root_id = asset.external_id.split(":", 1)[0]

        filename = Path(asset.remote_url.split("?", 1)[0]).name
        if not filename:
            raise RuntimeError(
                f"Could not determine filename from {asset.remote_url}")

        dest_dir = self.library_root / root_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        await self._download_file(asset.remote_url, dest_path)

        asset.status = AssetStatus.LOCAL
        asset.local_path = dest_path
        self._db.upsert_asset(asset)
        return asset

    async def download_composite(
        self,
        composite: CompositeAsset,
        resolution: str | None = None,
        recursive: bool = True,
    ) -> CompositeAsset:
        """Download assets contained in a composite (optionally recursively)."""
        if composite.source != self.plugin_id:
            raise ValueError(
                f"Composite is not from PolyHaven: {composite.source}")

        if not composite.children:
            composite = await self.expand_composite(composite)

        updated_children = []
        for child in composite.children:
            if isinstance(child, CompositeAsset):
                if recursive:
                    if not child.children:
                        child = await self.expand_composite(child)
                    updated_children.append(
                        await self.download_composite(child, resolution=resolution, recursive=True)
                    )
                else:
                    updated_children.append(child)
                continue

            if isinstance(child, Asset):
                if resolution is None or child.metadata.get("resolution") == resolution:
                    updated_children.append(await self.download_asset(child))
                else:
                    updated_children.append(child)
                continue

            updated_children.append(child)

        composite.children = updated_children
        return composite

    @property
    def can_download(self) -> bool:
        return True

    @property
    def can_remove(self) -> bool:
        return False

    def get_settings_schema(self, asset: Any) -> dict[str, Any] | None:
        """Return resolution settings schema for bulk downloads."""
        return {
            "resolution": {
                "type": "choice",
                "options": AVAILABLE_RESOLUTIONS,
                "default": DEFAULT_RESOLUTION,
            }
        }

    async def get_asset_info(self, external_id: str) -> dict[str, Any] | None:
        """Fetch detailed info for a specific PolyHaven asset ID."""
        try:
            url = f"{API_INFO}/{external_id}"
            value = await self._fetch_json(url)
            return value if isinstance(value, dict) else None
        except Exception as e:
            logger.error(f"Failed to fetch asset info for {external_id}: {e}")
            return None
