"""Tests for asset library plugins.

Note: These tests intentionally avoid requiring `pytest-asyncio` by driving async
plugin methods via `asyncio.run()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from uab.core.database import AssetDatabase
from uab.core.models import Asset, AssetStatus, AssetType, CompositeAsset, CompositeType, StandardAsset


class TestLocalLibraryPluginInit:
    """Tests for LocalLibraryPlugin initialization."""

    def test_plugin_id_is_local(self) -> None:
        """Plugin ID should be 'local'."""
        from uab.plugins.local import LocalLibraryPlugin

        assert LocalLibraryPlugin.plugin_id == "local"

    def test_display_name(self) -> None:
        """Display name should be descriptive."""
        from uab.plugins.local import LocalLibraryPlugin

        assert LocalLibraryPlugin.display_name == "Local Library"

    def test_can_download_is_false(self, tmp_path: Path) -> None:
        """Local plugin should not support downloads."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert plugin.can_download is False

    def test_can_remove_is_true(self, tmp_path: Path) -> None:
        """Local plugin should support removal."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert plugin.can_remove is True


class TestLocalLibraryPluginSearch:
    """Tests for LocalLibraryPlugin search functionality."""

    def test_search_returns_all_local_assets_when_query_empty(
        self, tmp_path: Path, make_asset
    ) -> None:
        """Empty query should return all local assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Add some local assets to database
        asset1 = make_asset(external_id="asset1", name="Test Asset 1")
        asset2 = make_asset(external_id="asset2", name="Test Asset 2")
        db.upsert_asset(asset1)
        db.upsert_asset(asset2)

        results = asyncio.run(plugin.search(""))

        assert len(results) == 2
        names = {a.name for a in results}
        assert "Test Asset 1" in names
        assert "Test Asset 2" in names

    def test_search_filters_by_query(self, tmp_path: Path, make_asset) -> None:
        """Search should filter by name query."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Add assets with different names
        asset1 = make_asset(external_id="brick", name="Red Brick Wall")
        asset2 = make_asset(external_id="wood", name="Oak Wood Planks")
        db.upsert_asset(asset1)
        db.upsert_asset(asset2)

        results = asyncio.run(plugin.search("Brick"))

        assert len(results) == 1
        assert results[0].name == "Red Brick Wall"

    def test_search_excludes_cloud_assets(self, tmp_path: Path, make_asset) -> None:
        """Search should only return LOCAL status assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Add local and cloud assets
        local_asset = make_asset(external_id="local", name="Local Asset")
        cloud_asset = make_asset(
            external_id="cloud",
            name="Cloud Asset",
            status=AssetStatus.CLOUD,
        )
        db.upsert_asset(local_asset)
        db.upsert_asset(cloud_asset)

        results = asyncio.run(plugin.search(""))

        assert len(results) == 1
        assert results[0].name == "Local Asset"


class TestLocalLibraryPluginDownload:
    """Tests for LocalLibraryPlugin download (should raise error)."""

    def test_download_raises_not_implemented(self, tmp_path: Path, make_asset) -> None:
        """download() should raise NotImplementedError."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)
        asset = make_asset()

        with pytest.raises(NotImplementedError):
            asyncio.run(plugin.download(asset))


class TestLocalLibraryPluginRemove:
    """Tests for LocalLibraryPlugin remove functionality."""

    def test_remove_deletes_asset_files(self, tmp_path: Path) -> None:
        """remove_asset should delete local files."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Create a real file to delete
        asset_file = tmp_path / "test_asset.hdr"
        asset_file.write_text("test content")

        asset = StandardAsset(
            source="local",
            external_id="test",
            name="Test",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=asset_file,
        )
        db.upsert_asset(asset)

        result = plugin.remove_asset(asset)

        assert result is True
        assert not asset_file.exists()
        assert db.get_asset_by_id(asset.id) is None

    def test_remove_deletes_asset_directory(self, tmp_path: Path) -> None:
        """remove_asset should delete asset directory."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        asset_dir = tmp_path / "test_asset"
        asset_dir.mkdir()
        (asset_dir / "file1.png").write_text("test")
        (asset_dir / "file2.png").write_text("test")

        asset = StandardAsset(
            source="local",
            external_id="test",
            name="Test",
            type=AssetType.TEXTURE,
            status=AssetStatus.LOCAL,
            local_path=asset_dir,
        )
        db.upsert_asset(asset)

        result = plugin.remove_asset(asset)

        assert result is True
        assert not asset_dir.exists()


class TestLocalLibraryPluginAddAssets:
    """Tests for LocalLibraryPlugin add_assets functionality."""

    def test_implements_supports_local_import_protocol(self, tmp_path: Path) -> None:
        """LocalLibraryPlugin should implement SupportsLocalImport protocol."""
        from uab.plugins.local import LocalLibraryPlugin
        from uab.core.interfaces import SupportsLocalImport

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert isinstance(plugin, SupportsLocalImport)

    def test_add_assets_from_directory_adds_hdri_files(self, tmp_path: Path) -> None:
        """Should add HDRI files (.hdr, .exr) with correct type."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "sunset.hdr").write_bytes(b"fake hdr")
        (assets_dir / "studio.exr").write_bytes(b"fake exr")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 2
        assert all(a.type == AssetType.HDRI for a in added)
        assert all(a.status == AssetStatus.LOCAL for a in added)
        assert {a.name for a in added} == {"sunset", "studio"}

    def test_add_assets_groups_hdri_variants_into_hdri_composite(self, tmp_path: Path) -> None:
        """Multiple HDRI variants of the same basename should group into an HDRI composite."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "hdris"
        assets_dir.mkdir()
        (assets_dir / "sunset_2k.hdr").write_bytes(b"fake hdr")
        (assets_dir / "sunset_4k.exr").write_bytes(b"fake exr")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)

        hdri = added[0]
        assert hdri.composite_type == CompositeType.HDRI
        assert hdri.name == "sunset"
        assert len(hdri.children) == 2
        assert all(isinstance(c, Asset) for c in hdri.children)
        assert all(c.asset_type == AssetType.HDRI for c in hdri.children)  # type: ignore[attr-defined]
        assert {c.metadata.get("resolution") for c in hdri.children} == {"2k", "4k"}
        assert {c.metadata.get("format") for c in hdri.children} == {"hdr", "exr"}

    def test_add_assets_groups_same_resolution_hdri_formats_prefers_hdr_first(self, tmp_path: Path) -> None:
        """When resolution ties, local HDRI grouping should order hdr before exr."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "hdris_same_res"
        assets_dir.mkdir()
        (assets_dir / "sunset_2k.exr").write_bytes(b"fake exr")
        (assets_dir / "sunset_2k.hdr").write_bytes(b"fake hdr")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)
        hdri = added[0]
        assert hdri.composite_type == CompositeType.HDRI
        assert len(hdri.children) == 2
        assert all(isinstance(c, Asset) for c in hdri.children)
        assert [
            (c.metadata.get("resolution"), c.metadata.get("format"))
            for c in hdri.children
            if isinstance(c, Asset)
        ] == [("2k", "hdr"), ("2k", "exr")]

    def test_add_assets_from_directory_groups_texture_files(self, tmp_path: Path) -> None:
        """Should group texture map files into a MATERIAL→TEXTURE→Asset tree."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "textures"
        assets_dir.mkdir()
        (assets_dir / "brick_diffuse.png").write_bytes(b"fake png")
        (assets_dir / "brick_normal.jpg").write_bytes(b"fake jpg")
        (assets_dir / "brick_roughness.tif").write_bytes(b"fake tif")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)

        material = added[0]
        assert material.composite_type == CompositeType.MATERIAL
        assert material.name == "brick"

        assert len(material.children) == 3
        assert all(isinstance(c, CompositeAsset) for c in material.children)
        assert all(c.composite_type == CompositeType.TEXTURE for c in material.children)

        for tex in material.children:
            assert tex.metadata.get("role") == tex.name
            assert tex.metadata.get("map_type") == tex.name
            assert len(tex.children) == 1
            assert isinstance(tex.children[0], Asset)
            assert tex.children[0].asset_type == AssetType.TEXTURE
            assert tex.children[0].status == AssetStatus.LOCAL

    def test_add_assets_grouped_files_create_nested_composite_with_resolutions(self, tmp_path: Path) -> None:
        """Grouped textures should become nested composites with resolution leaf assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        textures_dir = tmp_path / "textures"
        textures_dir.mkdir()
        (textures_dir / "brick_diffuse_2k.png").write_bytes(b"fake")
        (textures_dir / "brick_diffuse_4k.png").write_bytes(b"fake")
        (textures_dir / "brick_normal_2k.png").write_bytes(b"fake")

        added = plugin.add_assets(textures_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)

        material = added[0]
        assert material.composite_type == CompositeType.MATERIAL
        assert material.name == "brick"

        diffuse = next(
            c for c in material.children
            if isinstance(c, CompositeAsset) and c.name == "diffuse"
        )
        assert len(diffuse.children) == 2
        assert all(isinstance(a, Asset) for a in diffuse.children)
        assert {a.metadata.get("resolution") for a in diffuse.children} == {"2k", "4k"}

        normal = next(
            c for c in material.children
            if isinstance(c, CompositeAsset) and c.name == "normal"
        )
        assert len(normal.children) == 1
        assert isinstance(normal.children[0], Asset)
        assert normal.children[0].metadata.get("resolution") == "2k"

    def test_add_assets_mixed_grouped_and_standalone(self, tmp_path: Path) -> None:
        """Mixed imports should return composites plus standalone Assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "brick_diffuse_2k.png").write_bytes(b"fake")
        (assets_dir / "brick_normal_2k.png").write_bytes(b"fake")
        (assets_dir / "chair.obj").write_bytes(b"fake")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 2
        assert any(isinstance(i, CompositeAsset) and i.composite_type == CompositeType.MATERIAL for i in added)
        assert any(isinstance(i, Asset) and i.asset_type == AssetType.MODEL for i in added)

    def test_add_assets_grouping_disabled_returns_all_assets(self, tmp_path: Path) -> None:
        """When grouping is disabled, all imported files should be leaf Assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db, grouping_enabled=False)

        assets_dir = tmp_path / "textures"
        assets_dir.mkdir()
        (assets_dir / "brick_diffuse_2k.png").write_bytes(b"fake")
        (assets_dir / "brick_normal_2k.png").write_bytes(b"fake")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 2
        assert all(isinstance(i, Asset) for i in added)
        assert {i.asset_type for i in added if isinstance(i, Asset)} == {AssetType.TEXTURE}

    def test_add_assets_custom_grouping_pattern(self, tmp_path: Path) -> None:
        """Custom grouping patterns should be supported."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(
            db=db,
            grouping_enabled=True,
            grouping_pattern="{basename}-{maptype}-{resolution}.{ext}",
        )

        assets_dir = tmp_path / "textures"
        assets_dir.mkdir()
        (assets_dir / "brick-diffuse-2k.png").write_bytes(b"fake")
        (assets_dir / "brick-normal-2k.png").write_bytes(b"fake")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)
        assert added[0].composite_type == CompositeType.MATERIAL
        assert added[0].name == "brick"

    def test_add_assets_groups_model_variants_into_model_composite(self, tmp_path: Path) -> None:
        """Multiple model variants of the same basename should group into a MODEL composite."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "models"
        assets_dir.mkdir()
        (assets_dir / "chair.obj").write_bytes(b"fake obj")
        (assets_dir / "chair.fbx").write_bytes(b"fake fbx")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert isinstance(added[0], CompositeAsset)

        model = added[0]
        assert model.composite_type == CompositeType.MODEL
        assert model.name == "chair"
        assert len(model.children) == 2
        assert all(isinstance(c, Asset) for c in model.children)
        assert all(c.asset_type == AssetType.MODEL for c in model.children)  # type: ignore[attr-defined]
        assert {c.metadata.get("format") for c in model.children} == {"obj", "fbx"}

    def test_add_assets_from_directory_adds_model_files(self, tmp_path: Path) -> None:
        """Should add model files with correct type."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "models"
        assets_dir.mkdir()
        (assets_dir / "chair.obj").write_bytes(b"fake obj")
        (assets_dir / "table.fbx").write_bytes(b"fake fbx")
        (assets_dir / "lamp.usd").write_bytes(b"fake usd")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 3
        assert all(a.type == AssetType.MODEL for a in added)

    def test_add_assets_from_directory_recursive(self, tmp_path: Path) -> None:
        """Should recursively scan subdirectories."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        root_dir = tmp_path / "library"
        root_dir.mkdir()
        (root_dir / "hdri").mkdir()
        (root_dir / "hdri" / "outdoor").mkdir()
        (root_dir / "hdri" / "outdoor" / "sunset.hdr").write_bytes(b"fake")
        (root_dir / "textures").mkdir()
        (root_dir / "textures" / "brick.png").write_bytes(b"fake")

        added = plugin.add_assets(root_dir)

        assert len(added) == 2
        names = {a.name for a in added}
        assert "sunset" in names
        assert "brick" in names

    def test_add_assets_from_directory_skips_unsupported(self, tmp_path: Path) -> None:
        """Should skip files with unsupported extensions."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "mixed"
        assets_dir.mkdir()
        (assets_dir / "valid.hdr").write_bytes(b"fake hdr")
        (assets_dir / "readme.txt").write_text("readme")
        (assets_dir / "script.py").write_text("code")
        (assets_dir / "data.json").write_text("{}")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1
        assert added[0].name == "valid"

    def test_add_assets_from_directory_skips_existing(self, tmp_path: Path) -> None:
        """Should skip files already in database."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        file_path = assets_dir / "existing.hdr"
        file_path.write_bytes(b"fake hdr")

        existing_asset = StandardAsset(
            source="local",
            external_id=str(file_path.resolve()),
            name="existing",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=file_path,
        )
        db.upsert_asset(existing_asset)

        added = plugin.add_assets(assets_dir)

        assert len(added) == 0

    def test_add_assets_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty list for nonexistent path."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        nonexistent = tmp_path / "does_not_exist"

        added = plugin.add_assets(nonexistent)

        assert added == []

    def test_add_assets_persists_to_database(self, tmp_path: Path) -> None:
        """Added assets should be persisted to database."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "test.hdr").write_bytes(b"fake hdr")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 1

        db_asset = db.get_asset_by_external_id(
            source="local",
            external_id=str((assets_dir / "test.hdr").resolve()),
        )
        assert db_asset is not None
        assert db_asset.name == "test"
        assert db_asset.type == AssetType.HDRI
        assert db_asset.status == AssetStatus.LOCAL

    def test_add_assets_single_file(self, tmp_path: Path) -> None:
        """Should add a single file when passed directly."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        file_path = tmp_path / "single_hdri.hdr"
        file_path.write_bytes(b"fake hdr")

        added = plugin.add_assets(file_path)

        assert len(added) == 1
        assert added[0].name == "single_hdri"
        assert added[0].type == AssetType.HDRI
        assert added[0].local_path == file_path

    def test_add_assets_list_of_files(self, tmp_path: Path) -> None:
        """Should add multiple individual files from a list."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        file1 = tmp_path / "sunset.hdr"
        file2 = tmp_path / "brick.png"
        file3 = tmp_path / "chair.obj"
        file1.write_bytes(b"fake hdr")
        file2.write_bytes(b"fake png")
        file3.write_bytes(b"fake obj")

        added = plugin.add_assets([file1, file2, file3])

        assert len(added) == 3
        types = {a.type for a in added}
        assert AssetType.HDRI in types
        assert AssetType.TEXTURE in types
        assert AssetType.MODEL in types

    def test_add_assets_mixed_files_and_directories(self, tmp_path: Path) -> None:
        """Should handle a mix of files and directories."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "in_dir.hdr").write_bytes(b"fake")

        individual_file = tmp_path / "individual.png"
        individual_file.write_bytes(b"fake")

        added = plugin.add_assets([assets_dir, individual_file])

        assert len(added) == 2
        names = {a.name for a in added}
        assert "in_dir" in names
        assert "individual" in names

    def test_add_assets_skips_unsupported_file(self, tmp_path: Path) -> None:
        """Should skip individual files with unsupported extensions."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        valid_file = tmp_path / "valid.hdr"
        invalid_file = tmp_path / "invalid.txt"
        valid_file.write_bytes(b"fake hdr")
        invalid_file.write_text("not an asset")

        added = plugin.add_assets([valid_file, invalid_file])

        assert len(added) == 1
        assert added[0].name == "valid"

    def test_add_assets_empty_list_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty list for empty input."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        added = plugin.add_assets([])

        assert added == []


class TestPolyHavenPluginInit:
    """Tests for PolyHavenPlugin initialization."""

    def test_plugin_id_is_polyhaven(self) -> None:
        """Plugin ID should be 'polyhaven'."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        assert PolyHavenPlugin.plugin_id == "polyhaven"

    def test_display_name(self) -> None:
        """Display name should be descriptive."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        assert PolyHavenPlugin.display_name == "PolyHaven"

    def test_can_download_is_true(self, tmp_path: Path) -> None:
        """PolyHaven plugin should support downloads."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        assert plugin.can_download is True

    def test_can_remove_is_false(self, tmp_path: Path) -> None:
        """PolyHaven plugin should not directly support removal."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        assert plugin.can_remove is False


class TestPolyHavenPluginSettingsSchema:
    """Tests for PolyHavenPlugin settings schema."""

    def test_settings_schema_includes_resolution(self, tmp_path: Path) -> None:
        """Default settings schema should include resolution options."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        schema = plugin.get_settings_schema(object())

        assert schema is not None
        assert "resolution" in schema
        assert schema["resolution"]["type"] == "choice"
        assert "2k" in schema["resolution"]["options"]
        assert "4k" in schema["resolution"]["options"]

    def test_hdri_settings_schema_adds_format_checkbox_before_resolution(self, tmp_path: Path) -> None:
        """HDRI settings should show format checkbox above resolution."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")
        hdri = CompositeAsset(
            id="polyhaven-hdri_sky",
            source="polyhaven",
            external_id="hdri_sky",
            name="HDRI Sky",
            composite_type=CompositeType.HDRI,
            children=[],
        )

        schema = plugin.get_settings_schema(hdri)
        assert schema is not None
        assert list(schema.keys())[:2] == ["use_exr", "resolution"]
        assert schema["use_exr"]["type"] == "bool"
        assert schema["resolution"]["type"] == "choice"

    def test_settings_schema_resolution_options_only_include_local_hdri_lods(
        self, tmp_path: Path
    ) -> None:
        """Resolution picker should only include local, import-ready HDRI LODs."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        local_1k = Asset(
            id="polyhaven-sky:1k:hdr",
            source="polyhaven",
            external_id="sky:1k:hdr",
            name="sky_1k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=tmp_path / "sky_1k.hdr",
            metadata={"resolution": "1k", "format": "hdr"},
        )
        cloud_2k = Asset(
            id="polyhaven-sky:2k:hdr",
            source="polyhaven",
            external_id="sky:2k:hdr",
            name="sky_2k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
            metadata={"resolution": "2k", "format": "hdr"},
        )
        local_4k = Asset(
            id="polyhaven-sky:4k:exr",
            source="polyhaven",
            external_id="sky:4k:exr",
            name="sky_4k.exr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=tmp_path / "sky_4k.exr",
            metadata={"resolution": "4k", "format": "exr"},
        )

        hdri = CompositeAsset(
            id="polyhaven-sky",
            source="polyhaven",
            external_id="sky",
            name="Sky",
            composite_type=CompositeType.HDRI,
            children=[local_1k, cloud_2k, local_4k],
        )

        schema = plugin.get_settings_schema(hdri)
        assert schema is not None
        assert schema["resolution"]["options"] == ["1k", "4k"]
        assert schema["resolution"]["default"] == "4k"

    def test_settings_schema_resolution_options_use_local_nested_material_lods(
        self, tmp_path: Path
    ) -> None:
        """Nested MATERIAL trees should aggregate only local resolutions."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        diffuse = CompositeAsset(
            id="polyhaven-rusty_metal:diffuse",
            source="polyhaven",
            external_id="rusty_metal:diffuse",
            name="diffuse",
            composite_type=CompositeType.TEXTURE,
            metadata={"role": "diffuse", "map_type": "diffuse"},
            children=[
                Asset(
                    id="polyhaven-rusty_metal:diffuse:1k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:1k",
                    name="rusty_diff_1k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.LOCAL,
                    local_path=tmp_path / "rusty_diff_1k.png",
                    metadata={"resolution": "1k", "map_type": "diffuse"},
                ),
                Asset(
                    id="polyhaven-rusty_metal:diffuse:4k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:4k",
                    name="rusty_diff_4k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.CLOUD,
                    metadata={"resolution": "4k", "map_type": "diffuse"},
                ),
            ],
        )
        normal = CompositeAsset(
            id="polyhaven-rusty_metal:normal",
            source="polyhaven",
            external_id="rusty_metal:normal",
            name="normal",
            composite_type=CompositeType.TEXTURE,
            metadata={"role": "normal", "map_type": "normal"},
            children=[
                Asset(
                    id="polyhaven-rusty_metal:normal:2k",
                    source="polyhaven",
                    external_id="rusty_metal:normal:2k",
                    name="rusty_nor_2k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.LOCAL,
                    local_path=tmp_path / "rusty_nor_2k.png",
                    metadata={"resolution": "2k", "map_type": "normal"},
                )
            ],
        )
        material = CompositeAsset(
            id="polyhaven-rusty_metal",
            source="polyhaven",
            external_id="rusty_metal",
            name="Rusty Metal",
            composite_type=CompositeType.MATERIAL,
            children=[diffuse, normal],
        )

        schema = plugin.get_settings_schema(material)
        assert schema is not None
        assert schema["resolution"]["options"] == ["1k", "2k"]
        assert schema["resolution"]["default"] == "2k"


def _make_material(external_id: str, name: str, thumbnail_url: str | None = None) -> CompositeAsset:
    return CompositeAsset(
        id=f"polyhaven-{external_id}",
        source="polyhaven",
        external_id=external_id,
        name=name,
        composite_type=CompositeType.MATERIAL,
        thumbnail_url=thumbnail_url,
        thumbnail_path=None,
        metadata={"categories": ["test"]},
        children=[],
    )


class TestPolyHavenPluginCompositeTree:
    """Milestone 4: PolyHaven returns nested composite tree."""

    def test_search_returns_hdris_materials_and_models(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        hdris_response = {"sunset_hdri": {"name": "Sunset HDRI"}}
        textures_response = {"rusty_metal": {"name": "Rusty Metal"}}
        models_response = {"simple_chair": {"name": "Simple Chair"}}

        async def _fake_fetch(url: str, *args, **kwargs):  # noqa: ARG001
            if "t=hdris" in url:
                return hdris_response
            if "t=textures" in url:
                return textures_response
            if "t=models" in url:
                return models_response
            return {}

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = _fake_fetch
            results = asyncio.run(plugin.search(""))

        assert len(results) == 3
        by_type = {(r.composite_type, r.external_id)
                   for r in results if isinstance(r, CompositeAsset)}
        assert (CompositeType.HDRI, "sunset_hdri") in by_type
        assert (CompositeType.MATERIAL, "rusty_metal") in by_type
        assert (CompositeType.MODEL, "simple_chair") in by_type

    def test_search_returns_material_composites(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        mock_response = {
            "rusty_metal": {
                "name": "Rusty Metal",
                "categories": ["metal"],
                "thumbnail_url": "https://example.com/rusty.png",
            }
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            async def _fake_fetch(url: str, *args, **kwargs):  # noqa: ARG001
                return mock_response if "t=textures" in url else {}

            mock_fetch.side_effect = _fake_fetch

            results = asyncio.run(plugin.search(""))

        assert len(results) == 1
        item = results[0]
        assert isinstance(item, CompositeAsset)
        assert item.composite_type == CompositeType.MATERIAL
        assert item.external_id == "rusty_metal"
        assert item.thumbnail_url == "https://example.com/rusty.png"
        assert item.metadata.get("categories") == ["metal"]
        assert item.children == []

    def test_search_attaches_cached_status_hints_for_lazy_composites(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        root = CompositeAsset(
            id="polyhaven-sunset_hdri",
            source="polyhaven",
            external_id="sunset_hdri",
            name="Sunset HDRI",
            composite_type=CompositeType.HDRI,
            children=[],
        )
        local_path = plugin.library_root / "sunset_hdri" / "sunset_2k.hdr"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(b"data")

        local_asset = Asset(
            id="polyhaven-sunset_hdri:2k:hdr",
            source="polyhaven",
            external_id="sunset_hdri:2k:hdr",
            name="sunset_2k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=local_path,
            remote_url="https://example.com/sunset_2k.hdr",
            metadata={"resolution": "2k", "format": "hdr"},
        )
        cloud_asset = Asset(
            id="polyhaven-sunset_hdri:4k:hdr",
            source="polyhaven",
            external_id="sunset_hdri:4k:hdr",
            name="sunset_4k.hdr",
            asset_type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
            local_path=None,
            remote_url="https://example.com/sunset_4k.hdr",
            metadata={"resolution": "4k", "format": "hdr"},
        )

        db.upsert_composite(root)
        db.set_composite_children(root.id, [local_asset, cloud_asset])

        async def _fake_fetch(url: str, *args, **kwargs):  # noqa: ARG001
            if "t=hdris" in url:
                return {"sunset_hdri": {"name": "Sunset HDRI"}}
            return {}

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = _fake_fetch
            results = asyncio.run(plugin.search(""))

        assert len(results) == 1
        item = results[0]
        assert isinstance(item, CompositeAsset)
        assert item.children == []  # still lazy until user expands
        assert getattr(item, "_ui_display_status_hint", None) == AssetStatus.CLOUD
        assert getattr(item, "_ui_is_mixed_hint", None) is True

    def test_expand_composite_creates_texture_children(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        material = _make_material("rusty_metal", "Rusty Metal")
        manifest = {
            "diffuse": {
                "1k": {"png": {"url": "https://example.com/rusty_diff_1k.png", "size": 10}},
                "2k": {"png": {"url": "https://example.com/rusty_diff_2k.png", "size": 20}},
            },
            "normal": {
                "1k": {"png": {"url": "https://example.com/rusty_nor_1k.png"}},
                "2k": {"png": {"url": "https://example.com/rusty_nor_2k.png"}},
            },
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = manifest
            expanded = asyncio.run(plugin.expand_composite(material))

        assert isinstance(expanded, CompositeAsset)
        assert expanded.composite_type == CompositeType.MATERIAL
        assert len(expanded.children) == 2
        assert all(isinstance(c, CompositeAsset) for c in expanded.children)
        assert {c.metadata.get("map_type") for c in expanded.children} == {
            "diffuse", "normal"}
        assert all(c.composite_type ==
                   CompositeType.TEXTURE for c in expanded.children)

        # persisted in DB
        db_children = db.get_composite_children(expanded.id)
        assert len(db_children) == 2

    def test_expand_texture_creates_asset_children(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        texture = CompositeAsset(
            id="polyhaven-rusty_metal:diffuse",
            source="polyhaven",
            external_id="rusty_metal:diffuse",
            name="diffuse",
            composite_type=CompositeType.TEXTURE,
            metadata={"role": "diffuse", "map_type": "diffuse"},
            children=[],
        )

        manifest = {
            "diffuse": {
                "1k": {"png": {"url": "https://example.com/rusty_diff_1k.png", "size": 10}},
                "2k": {"png": {"url": "https://example.com/rusty_diff_2k.png", "size": 20}},
            },
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = manifest
            expanded = asyncio.run(plugin.expand_composite(texture))

        assert expanded.composite_type == CompositeType.TEXTURE
        assert len(expanded.children) == 2
        assert all(isinstance(a, Asset) for a in expanded.children)

        # Verify URLs + metadata
        by_res = {a.metadata["resolution"]: a for a in expanded.children}
        assert by_res["1k"].remote_url == "https://example.com/rusty_diff_1k.png"
        assert by_res["1k"].metadata == {
            "resolution": "1k", "map_type": "diffuse"}
        assert by_res["2k"].file_size == 20

        # Persisted in DB
        db_children = db.get_composite_children(expanded.id)
        assert len(db_children) == 2

    def test_expand_hdri_creates_asset_children(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        thumb_url = "https://example.com/sunset_thumb.png"
        hdri = CompositeAsset(
            id="polyhaven-sunset_hdri",
            source="polyhaven",
            external_id="sunset_hdri",
            name="Sunset HDRI",
            composite_type=CompositeType.HDRI,
            thumbnail_url=thumb_url,
            metadata={"categories": ["outdoor"]},
            children=[],
        )

        manifest = {
            "hdri": {
                "1k": {"hdr": {"url": "https://example.com/sunset_1k.hdr", "size": 10}},
                "2k": {
                    "hdr": {"url": "https://example.com/sunset_2k.hdr", "size": 15},
                    "exr": {"url": "https://example.com/sunset_2k.exr", "size": 20},
                },
            }
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = manifest
            expanded = asyncio.run(plugin.expand_composite(hdri))

        assert expanded.composite_type == CompositeType.HDRI
        assert len(expanded.children) == 3
        assert all(isinstance(a, Asset) for a in expanded.children)
        assert [
            (a.metadata["resolution"], a.metadata["format"])
            for a in expanded.children
        ] == [("1k", "hdr"), ("2k", "hdr"), ("2k", "exr")]

        by_variant = {
            (a.metadata["resolution"], a.metadata["format"]): a
            for a in expanded.children
        }
        assert by_variant[("1k", "hdr")].remote_url == "https://example.com/sunset_1k.hdr"
        assert by_variant[("1k", "hdr")].thumbnail_url == thumb_url
        assert by_variant[("2k", "hdr")].remote_url == "https://example.com/sunset_2k.hdr"
        assert by_variant[("2k", "hdr")].file_size == 15
        assert by_variant[("2k", "exr")].remote_url == "https://example.com/sunset_2k.exr"
        assert by_variant[("2k", "exr")].thumbnail_url == thumb_url
        assert by_variant[("2k", "exr")].file_size == 20

        db_children = db.get_composite_children(expanded.id)
        assert len(db_children) == 3


    def test_local_library_groups_downloaded_polyhaven_hdri_into_single_composite(self, tmp_path: Path) -> None:
        """Downloaded PolyHaven HDRIs should appear as a single HDRI composite locally."""
        from uab.plugins.local import LocalLibraryPlugin
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        library_root = tmp_path / "library"

        poly = PolyHavenPlugin(db=db, library_root=library_root)
        local = LocalLibraryPlugin(db=db, library_root=library_root)

        hdri = CompositeAsset(
            id="polyhaven-sunset_hdri",
            source="polyhaven",
            external_id="sunset_hdri",
            name="Sunset HDRI",
            composite_type=CompositeType.HDRI,
            metadata={"categories": ["outdoor"]},
            children=[],
        )

        manifest = {
            "hdri": {
                "1k": {"hdr": {"url": "https://example.com/sunset_1k.hdr", "size": 10}},
                "2k": {
                    "hdr": {"url": "https://example.com/sunset_2k.hdr", "size": 20},
                    "exr": {"url": "https://example.com/sunset_2k.exr", "size": 30},
                },
            }
        }

        async def _fake_download(url: str, dest_path: Path, *args, **kwargs) -> Path:  # noqa: ARG001
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"data")
            return dest_path

        with patch.object(poly, "_fetch_json", new_callable=AsyncMock) as mock_fetch, patch.object(
            poly, "_download_file", new_callable=AsyncMock
        ) as mock_dl:
            mock_fetch.return_value = manifest
            mock_dl.side_effect = _fake_download

            expanded = asyncio.run(poly.expand_composite(hdri))
            asyncio.run(poly.download_composite(expanded, resolution="2k"))

        results = asyncio.run(local.search("sunset"))

        assert len(results) == 1
        assert isinstance(results[0], CompositeAsset)

        local_hdri = results[0]
        assert local_hdri.source == "polyhaven"
        assert local_hdri.composite_type == CompositeType.HDRI
        assert local_hdri.name == "Sunset HDRI"
        assert len(local_hdri.children) == 3
        assert all(isinstance(c, Asset) for c in local_hdri.children)

        assert [
            (c.metadata.get("resolution"), c.metadata.get("format"))
            for c in local_hdri.children
            if isinstance(c, Asset)
        ] == [("2k", "hdr"), ("2k", "exr"), ("1k", "hdr")]

        by_variant = {
            (c.metadata.get("resolution"), c.metadata.get("format")): c
            for c in local_hdri.children
            if isinstance(c, Asset)
        }
        assert by_variant[("2k", "hdr")].status == AssetStatus.LOCAL
        assert by_variant[("2k", "exr")].status == AssetStatus.LOCAL
        assert by_variant[("1k", "hdr")].status == AssetStatus.CLOUD
        assert local_hdri.is_mixed is True

    def test_expand_model_creates_asset_children(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        thumb_url = "https://example.com/chair_thumb.png"
        model = CompositeAsset(
            id="polyhaven-simple_chair",
            source="polyhaven",
            external_id="simple_chair",
            name="Simple Chair",
            composite_type=CompositeType.MODEL,
            thumbnail_url=thumb_url,
            metadata={"categories": ["furniture"]},
            children=[],
        )

        manifest = {
            "gltf": {
                "1k": {"gltf": {"url": "https://example.com/chair_1k.gltf", "size": 100}},
                "2k": {"gltf": {"url": "https://example.com/chair_2k.gltf"}},
            },
            "fbx": {
                "1k": {"fbx": {"url": "https://example.com/chair_1k.fbx", "size": 200}},
            },
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = manifest
            expanded = asyncio.run(plugin.expand_composite(model))

        assert expanded.composite_type == CompositeType.MODEL
        assert len(expanded.children) == 3
        assert all(isinstance(a, Asset) for a in expanded.children)
        assert all(a.asset_type == AssetType.MODEL for a in expanded.children)
        assert {a.metadata.get("format")
                for a in expanded.children} == {"gltf", "fbx"}
        assert any(
            a.remote_url == "https://example.com/chair_1k.fbx" for a in expanded.children)
        assert all(a.thumbnail_url == thumb_url for a in expanded.children)

        db_children = db.get_composite_children(expanded.id)
        assert len(db_children) == 3

    def test_download_asset_downloads_single_file(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        asset = Asset(
            id="polyhaven-rusty_metal:diffuse:2k",
            source="polyhaven",
            external_id="rusty_metal:diffuse:2k",
            name="rusty_diff_2k.png",
            asset_type=AssetType.TEXTURE,
            status=AssetStatus.CLOUD,
            remote_url="https://example.com/rusty_diff_2k.png",
            metadata={"resolution": "2k", "map_type": "diffuse"},
        )

        async def _fake_download(url: str, dest_path: Path, *args, **kwargs) -> Path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"test")
            return dest_path

        with patch.object(plugin, "_download_file", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = _fake_download
            updated = asyncio.run(plugin.download_asset(asset))

        assert updated.status == AssetStatus.LOCAL
        assert updated.local_path is not None
        assert updated.local_path.exists()

        db_asset = db.get_asset_by_external_id("polyhaven", asset.external_id)
        assert db_asset is not None
        assert db_asset.status == AssetStatus.LOCAL

    def test_download_composite_with_resolution_filter(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        # Build a fully-expanded tree: material -> texture -> assets
        material = _make_material("rusty_metal", "Rusty Metal")
        texture = CompositeAsset(
            id="polyhaven-rusty_metal:diffuse",
            source="polyhaven",
            external_id="rusty_metal:diffuse",
            name="diffuse",
            composite_type=CompositeType.TEXTURE,
            metadata={"role": "diffuse", "map_type": "diffuse"},
            children=[
                Asset(
                    id="polyhaven-rusty_metal:diffuse:1k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:1k",
                    name="rusty_diff_1k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.CLOUD,
                    remote_url="https://example.com/rusty_diff_1k.png",
                    metadata={"resolution": "1k", "map_type": "diffuse"},
                ),
                Asset(
                    id="polyhaven-rusty_metal:diffuse:2k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:2k",
                    name="rusty_diff_2k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.CLOUD,
                    remote_url="https://example.com/rusty_diff_2k.png",
                    metadata={"resolution": "2k", "map_type": "diffuse"},
                ),
            ],
        )
        material.children = [texture]

        async def _fake_download(url: str, dest_path: Path, *args, **kwargs) -> Path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"test")
            return dest_path

        with patch.object(plugin, "_download_file", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = _fake_download
            updated = asyncio.run(
                plugin.download_composite(material, resolution="2k"))

        # only 2k should be local
        updated_texture = updated.children[0]
        assert isinstance(updated_texture, CompositeAsset)
        by_res = {a.metadata["resolution"]
            : a for a in updated_texture.children if isinstance(a, Asset)}
        assert by_res["1k"].status == AssetStatus.CLOUD
        assert by_res["2k"].status == AssetStatus.LOCAL

    def test_download_composite_without_filter_downloads_all(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        material = _make_material("rusty_metal", "Rusty Metal")
        texture = CompositeAsset(
            id="polyhaven-rusty_metal:diffuse",
            source="polyhaven",
            external_id="rusty_metal:diffuse",
            name="diffuse",
            composite_type=CompositeType.TEXTURE,
            metadata={"role": "diffuse", "map_type": "diffuse"},
            children=[
                Asset(
                    id="polyhaven-rusty_metal:diffuse:1k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:1k",
                    name="rusty_diff_1k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.CLOUD,
                    remote_url="https://example.com/rusty_diff_1k.png",
                    metadata={"resolution": "1k", "map_type": "diffuse"},
                ),
                Asset(
                    id="polyhaven-rusty_metal:diffuse:2k",
                    source="polyhaven",
                    external_id="rusty_metal:diffuse:2k",
                    name="rusty_diff_2k.png",
                    asset_type=AssetType.TEXTURE,
                    status=AssetStatus.CLOUD,
                    remote_url="https://example.com/rusty_diff_2k.png",
                    metadata={"resolution": "2k", "map_type": "diffuse"},
                ),
            ],
        )
        material.children = [texture]

        async def _fake_download(url: str, dest_path: Path, *args, **kwargs) -> Path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"test")
            return dest_path

        with patch.object(plugin, "_download_file", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = _fake_download
            updated = asyncio.run(plugin.download_composite(material))

        updated_texture = updated.children[0]
        assert isinstance(updated_texture, CompositeAsset)
        assert all(isinstance(a, Asset) and a.status ==
                   AssetStatus.LOCAL for a in updated_texture.children)


class TestPolyHavenPluginErrorHandling:
    """Tests for PolyHavenPlugin error handling (API failures)."""

    def test_search_skips_failed_asset_type_and_returns_others(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        hdris_response = {"sunset_hdri": {"name": "Sunset HDRI"}}
        models_response = {"simple_chair": {"name": "Simple Chair"}}

        async def _fake_fetch(url: str, *args, **kwargs):  # noqa: ARG001
            if "t=hdris" in url:
                return hdris_response
            if "t=models" in url:
                return models_response
            if "t=textures" in url:
                raise RuntimeError("boom")
            return {}

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = _fake_fetch
            results = asyncio.run(plugin.search(""))

        # Textures failed, HDRIs + Models still return.
        assert len(results) == 2
        by_type = {(r.composite_type, r.external_id)
                   for r in results if isinstance(r, CompositeAsset)}
        assert (CompositeType.HDRI, "sunset_hdri") in by_type
        assert (CompositeType.MODEL, "simple_chair") in by_type

    def test_get_asset_info_returns_none_on_api_failure(self, tmp_path: Path) -> None:
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("boom")
            value = asyncio.run(plugin.get_asset_info("rusty_metal"))

        assert value is None


class TestBaseAssetPluginInit:
    """Tests for SharedAssetLibraryUtils initialization."""

    def test_library_root_is_created(self, tmp_path: Path) -> None:
        """Plugin should create library root directory."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query: str):
                return []

            @property
            def can_download(self):
                return False

            @property
            def can_remove(self):
                return False

        db = AssetDatabase(db_path=tmp_path / "test.db")
        lib_root = tmp_path / "library"
        plugin = TestPlugin(db=db, library_root=lib_root)

        assert lib_root.exists()
        assert plugin.library_root == lib_root / "test"

    def test_thumbnail_cache_is_accessible(self, tmp_path: Path) -> None:
        """Plugin should have thumbnail cache path."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query: str):
                return []

            @property
            def can_download(self):
                return False

            @property
            def can_remove(self):
                return False

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = TestPlugin(db=db, library_root=tmp_path / "library")

        assert plugin._thumbnail_cache_dir is not None

    def test_get_thumbnail_cache_path_returns_none_if_not_cached(
        self, tmp_path: Path, make_asset
    ) -> None:
        """get_thumbnail_cache_path should return None if not cached."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query: str):
                return []

            @property
            def can_download(self):
                return False

            @property
            def can_remove(self):
                return False

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = TestPlugin(db=db, library_root=tmp_path / "library")
        asset = make_asset()

        result = plugin.get_thumbnail_cache_path(asset)
        assert result is None


class TestPluginRegistration:
    """Tests for plugin auto-registration."""

    def test_all_plugins_are_registered(self) -> None:
        """All plugins should be registered in the registry."""
        from uab import plugins  # noqa: F401
        from uab.plugins import MockPlugin, LocalLibraryPlugin, PolyHavenPlugin

        assert MockPlugin.plugin_id == "mock"
        assert LocalLibraryPlugin.plugin_id == "local"
        assert PolyHavenPlugin.plugin_id == "polyhaven"

    def test_can_instantiate_registered_plugins(self, tmp_path: Path) -> None:
        """Should be able to instantiate plugins from registry."""
        from uab.plugins import MockPlugin, LocalLibraryPlugin, PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")

        mock = MockPlugin()
        assert mock.plugin_id == "mock"

        local = LocalLibraryPlugin(db=db, library_root=tmp_path / "lib")
        assert local.plugin_id == "local"

        polyhaven = PolyHavenPlugin(db=db, library_root=tmp_path / "lib")
        assert polyhaven.plugin_id == "polyhaven"
