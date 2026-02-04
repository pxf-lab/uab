"""End-to-end-ish tests for search → expand → download → import flows (Milestone 9.7)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from uab.core.database import AssetDatabase
from uab.core.interfaces import RenderStrategy
from uab.core.models import CompositeAsset, CompositeType, StandardAsset


class DummyMaterialStrategy(RenderStrategy):
    """Minimal strategy to capture material imports without Houdini."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Path], dict[str, Any]]] = []

    def get_required_texture_maps(self) -> set[str]:
        return {"diffuse", "base_color", "albedo"}

    def get_optional_texture_maps(self) -> set[str]:
        return {"normal", "roughness", "metallic", "ao", "displacement"}

    def create_environment_light(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def update_environment_light(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        return None

    def create_material_from_textures(
        self, name: str, textures: dict[str, Path], options: dict[str, Any]
    ) -> Any:  # noqa: ANN401
        self.calls.append((name, dict(textures), dict(options)))
        return {"name": name, "textures": textures}

    def create_material(self, composite: CompositeAsset, options: dict[str, Any]) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def update_material(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        return None


def test_search_expand_download_import_and_local_visibility(tmp_path: Path) -> None:
    """PolyHaven download should become visible in Local plugin and importable as a MATERIAL."""
    from uab.core.models import Asset, AssetStatus, AssetType
    from uab.integrations.houdini.integration import HoudiniIntegration
    from uab.plugins.local import LocalLibraryPlugin
    from uab.plugins.polyhaven import PolyHavenPlugin

    db = AssetDatabase(db_path=tmp_path / "test.db")
    library_root = tmp_path / "library"

    poly = PolyHavenPlugin(db=db, library_root=library_root, asset_type_filter=AssetType.TEXTURE)
    local = LocalLibraryPlugin(db=db, library_root=library_root)

    # Search results (materials only due to asset_type_filter)
    assets_response = {
        "rusty_metal": {
            "name": "Rusty Metal",
            "categories": ["metal"],
            "thumbnail_url": "https://example.com/rusty.png",
        }
    }

    manifest = {
        "diffuse": {
            "1k": {"png": {"url": "https://example.com/rusty_diff_1k.png", "size": 10}},
            "2k": {"png": {"url": "https://example.com/rusty_diff_2k.png", "size": 20}},
        },
        "normal": {
            "2k": {"png": {"url": "https://example.com/rusty_nor_2k.png", "size": 21}},
        },
    }

    async def _fake_fetch(url: str, *args, **kwargs):  # noqa: ARG001
        if "assets?t=textures" in url:
            return assets_response
        if "/files/rusty_metal" in url:
            return manifest
        return {}

    async def _fake_download(url: str, dest_path: Path, *args, **kwargs) -> Path:  # noqa: ARG001
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"data")
        return dest_path

    with patch.object(poly, "_fetch_json", new_callable=AsyncMock) as mock_fetch, patch.object(
        poly, "_download_file", new_callable=AsyncMock
    ) as mock_dl:
        mock_fetch.side_effect = _fake_fetch
        mock_dl.side_effect = _fake_download

        results = asyncio.run(poly.search(""))
        assert len(results) == 1
        material = results[0]
        assert isinstance(material, CompositeAsset)
        assert material.composite_type == CompositeType.MATERIAL

        # Expand (to get TEXTURE children), then download just 2k.
        expanded = asyncio.run(poly.expand_composite(material))
        downloaded = asyncio.run(poly.download_composite(expanded, resolution="2k"))

    # Verify downloaded composite has LOCAL assets at 2k
    tex_nodes = [c for c in downloaded.children if isinstance(c, CompositeAsset)]
    assert tex_nodes and all(t.composite_type == CompositeType.TEXTURE for t in tex_nodes)

    # There should be at least one LOCAL 2k asset across the tree
    leaf_assets = downloaded.get_all_assets()
    assert any(
        isinstance(a, Asset)
        and a.status == AssetStatus.LOCAL
        and a.metadata.get("resolution") == "2k"
        and a.local_path
        and a.local_path.exists()
        for a in leaf_assets
    )

    # Import traversal should pick only LOCAL 2k variants.
    integration = HoudiniIntegration()
    strategy = DummyMaterialStrategy()
    integration._strategies = {"karma": strategy}

    integration._import_material(downloaded, {"renderer": "karma", "resolution": "2k"})

    assert strategy.calls
    name, textures, _opts = strategy.calls[0]
    assert name == "Rusty Metal"
    assert "diffuse" in textures
    assert textures["diffuse"].name.endswith("2k.png")

    # Local plugin should see downloaded PolyHaven assets in its search.
    local_results = asyncio.run(local.search("rusty"))
    assert any(getattr(item, "source", None) == "polyhaven" for item in local_results)

