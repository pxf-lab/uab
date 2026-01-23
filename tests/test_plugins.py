"""Tests for asset library plugins."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from uab.core.database import AssetDatabase
from uab.core.models import AssetStatus, AssetType, StandardAsset


class TestLocalLibraryPluginInit:
    """Tests for LocalLibraryPlugin initialization.

    TODO: are these really necessary?"""

    def test_plugin_id_is_local(self):
        """Plugin ID should be 'local'."""
        from uab.plugins.local import LocalLibraryPlugin

        assert LocalLibraryPlugin.plugin_id == "local"

    def test_display_name(self):
        """Display name should be descriptive."""
        from uab.plugins.local import LocalLibraryPlugin

        assert LocalLibraryPlugin.display_name == "Local Library"

    def test_can_download_is_false(self, tmp_path: Path):
        """Local plugin should not support downloads."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert plugin.can_download is False

    def test_can_remove_is_true(self, tmp_path: Path):
        """Local plugin should support removal."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert plugin.can_remove is True


class TestLocalLibraryPluginSearch:
    """Tests for LocalLibraryPlugin search functionality."""

    @pytest.mark.asyncio
    async def test_search_returns_all_local_assets_when_query_empty(
        self, tmp_path: Path, make_asset
    ):
        """Empty query should return all local assets."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Add some local assets to database
        asset1 = make_asset(external_id="asset1", name="Test Asset 1")
        asset2 = make_asset(external_id="asset2", name="Test Asset 2")
        db.upsert_asset(asset1)
        db.upsert_asset(asset2)

        results = await plugin.search("")

        assert len(results) == 2
        names = {a.name for a in results}
        assert "Test Asset 1" in names
        assert "Test Asset 2" in names

    @pytest.mark.asyncio
    async def test_search_filters_by_query(self, tmp_path: Path, make_asset):
        """Search should filter by name query."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        # Add assets with different names
        asset1 = make_asset(external_id="brick", name="Red Brick Wall")
        asset2 = make_asset(external_id="wood", name="Oak Wood Planks")
        db.upsert_asset(asset1)
        db.upsert_asset(asset2)

        results = await plugin.search("Brick")

        assert len(results) == 1
        assert results[0].name == "Red Brick Wall"

    @pytest.mark.asyncio
    async def test_search_excludes_cloud_assets(self, tmp_path: Path, make_asset):
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

        results = await plugin.search("")

        assert len(results) == 1
        assert results[0].name == "Local Asset"


class TestLocalLibraryPluginDownload:
    """Tests for LocalLibraryPlugin download (should raise error)."""

    @pytest.mark.asyncio
    async def test_download_raises_not_implemented(self, tmp_path: Path, make_asset):
        """download() should raise NotImplementedError."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)
        asset = make_asset()

        with pytest.raises(NotImplementedError):
            await plugin.download(asset)


class TestLocalLibraryPluginRemove:
    """Tests for LocalLibraryPlugin remove functionality."""

    def test_remove_deletes_asset_files(self, tmp_path: Path):
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

    def test_remove_deletes_asset_directory(self, tmp_path: Path):
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

    def test_implements_supports_local_import_protocol(self, tmp_path: Path):
        """LocalLibraryPlugin should implement SupportsLocalImport protocol."""
        from uab.plugins.local import LocalLibraryPlugin
        from uab.core.interfaces import SupportsLocalImport

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assert isinstance(plugin, SupportsLocalImport)

    def test_add_assets_from_directory_adds_hdri_files(self, tmp_path: Path):
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

    def test_add_assets_from_directory_adds_texture_files(self, tmp_path: Path):
        """Should add texture files with correct type."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        assets_dir = tmp_path / "textures"
        assets_dir.mkdir()
        (assets_dir / "brick_diffuse.png").write_bytes(b"fake png")
        (assets_dir / "brick_normal.jpg").write_bytes(b"fake jpg")
        (assets_dir / "brick_roughness.tif").write_bytes(b"fake tif")

        added = plugin.add_assets(assets_dir)

        assert len(added) == 3
        assert all(a.type == AssetType.TEXTURE for a in added)

    def test_add_assets_from_directory_adds_model_files(self, tmp_path: Path):
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

    def test_add_assets_from_directory_recursive(self, tmp_path: Path):
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

    def test_add_assets_from_directory_skips_unsupported(self, tmp_path: Path):
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

    def test_add_assets_from_directory_skips_existing(self, tmp_path: Path):
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

    def test_add_assets_nonexistent_returns_empty(self, tmp_path: Path):
        """Should return empty list for nonexistent path."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        nonexistent = tmp_path / "does_not_exist"

        added = plugin.add_assets(nonexistent)

        assert added == []

    def test_add_assets_persists_to_database(self, tmp_path: Path):
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

    def test_add_assets_single_file(self, tmp_path: Path):
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

    def test_add_assets_list_of_files(self, tmp_path: Path):
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

    def test_add_assets_mixed_files_and_directories(self, tmp_path: Path):
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

    def test_add_assets_skips_unsupported_file(self, tmp_path: Path):
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

    def test_add_assets_empty_list_returns_empty(self, tmp_path: Path):
        """Should return empty list for empty input."""
        from uab.plugins.local import LocalLibraryPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = LocalLibraryPlugin(db=db)

        added = plugin.add_assets([])

        assert added == []


class TestPolyHavenPluginInit:
    """Tests for PolyHavenPlugin initialization."""

    def test_plugin_id_is_polyhaven(self):
        """Plugin ID should be 'polyhaven'."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        assert PolyHavenPlugin.plugin_id == "polyhaven"

    def test_display_name(self):
        """Display name should be descriptive."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        assert PolyHavenPlugin.display_name == "PolyHaven"

    def test_can_download_is_true(self, tmp_path: Path):
        """PolyHaven plugin should support downloads."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        assert plugin.can_download is True

    def test_can_remove_is_false(self, tmp_path: Path):
        """PolyHaven plugin should not directly support removal."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        assert plugin.can_remove is False


class TestPolyHavenPluginSettingsSchema:
    """Tests for PolyHavenPlugin settings schema."""

    def test_settings_schema_includes_resolution(self, tmp_path: Path, make_asset):
        """Settings schema should include resolution options."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")
        asset = make_asset(type=AssetType.HDRI)

        schema = plugin.get_settings_schema(asset)

        assert schema is not None
        assert "resolution" in schema
        assert schema["resolution"]["type"] == "choice"
        assert "2k" in schema["resolution"]["options"]
        assert "4k" in schema["resolution"]["options"]


class TestPolyHavenPluginSearch:
    """Tests for PolyHavenPlugin search functionality."""

    @pytest.mark.asyncio
    async def test_search_calls_api(self, tmp_path: Path):
        """Search should call the PolyHaven API."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        mock_response = {
            "test_hdri": {
                "name": "Test HDRI",
                "categories": ["outdoor"],
                "tags": ["sky"],
            }
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_response

            results = await plugin.search("")

            assert mock_fetch.called

    @pytest.mark.asyncio
    async def test_search_filters_by_query(self, tmp_path: Path):
        """Search should filter results by query string."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        mock_response = {
            "sunset_beach": {"name": "Sunset Beach"},
            "forest_clearing": {"name": "Forest Clearing"},
            "studio_light": {"name": "Studio Light"},
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_response

            results = await plugin.search("sunset")

            matching = [r for r in results if "sunset" in r.name.lower()]
            assert len(matching) >= 1

    @pytest.mark.asyncio
    async def test_search_marks_downloaded_assets_as_local(self, tmp_path: Path):
        """Already downloaded assets should have LOCAL status."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        existing_asset = StandardAsset(
            source="polyhaven",
            external_id="existing_hdri",
            name="Existing HDRI",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=tmp_path / "library" / "existing_hdri",
        )
        db.upsert_asset(existing_asset)

        mock_response = {
            "existing_hdri": {"name": "Existing HDRI"},
            "new_hdri": {"name": "New HDRI"},
        }

        with patch.object(plugin, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_response

            results = await plugin.search("")

            existing = next(
                (r for r in results if r.external_id == "existing_hdri"), None
            )
            new = next(
                (r for r in results if r.external_id == "new_hdri"), None)

            if existing:
                assert existing.status == AssetStatus.LOCAL
            if new:
                assert new.status == AssetStatus.CLOUD


class TestPolyHavenPluginDownload:
    """Tests for PolyHavenPlugin download functionality."""

    @pytest.mark.asyncio
    async def test_download_rejects_non_polyhaven_assets(self, tmp_path: Path):
        """download() should reject assets from other sources."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        plugin = PolyHavenPlugin(db=db, library_root=tmp_path / "library")

        asset = StandardAsset(
            source="other_source",
            external_id="test",
            name="Test",
            type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
        )

        with pytest.raises(ValueError, match="not from PolyHaven"):
            await plugin.download(asset)

    @pytest.mark.asyncio
    async def test_download_creates_asset_directory(self, tmp_path: Path):
        """download() should create the asset directory."""
        from uab.plugins.polyhaven import PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")
        library_root = tmp_path / "library"
        plugin = PolyHavenPlugin(db=db, library_root=library_root)

        asset = StandardAsset(
            source="polyhaven",
            external_id="test_hdri",
            name="Test HDRI",
            type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
        )

        files_response = {
            "hdri": {
                "2k": {
                    "hdr": {"url": "https://example.com/test_hdri_2k.hdr"}
                }
            }
        }

        with patch.object(
            plugin, "_fetch_json", new_callable=AsyncMock
        ) as mock_fetch, patch.object(
            plugin, "_download_file", new_callable=AsyncMock
        ) as mock_download, patch.object(
            plugin, "download_thumbnail", new_callable=AsyncMock
        ) as mock_thumb:
            mock_fetch.return_value = files_response
            mock_download.return_value = library_root / \
                "polyhaven" / "test_hdri" / "test_hdri_2k.hdr"
            mock_thumb.return_value = None

            result = await plugin.download(asset, resolution="2k")

            assert result.status == AssetStatus.LOCAL
            assert result.local_path is not None


class TestBaseAssetPluginInit:
    """Tests for BaseAssetPlugin initialization."""

    def test_library_root_is_created(self, tmp_path: Path):
        """Plugin should create library root directory."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query):
                return []

            async def download(self, asset, resolution=None):
                return asset

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

    def test_thumbnail_cache_is_accessible(self, tmp_path: Path):
        """Plugin should have thumbnail cache path."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query):
                return []

            async def download(self, asset, resolution=None):
                return asset

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
    ):
        """get_thumbnail_cache_path should return None if not cached."""
        from uab.plugins.base import SharedAssetLibraryUtils

        class TestPlugin(SharedAssetLibraryUtils):
            plugin_id = "test"
            display_name = "Test"

            async def search(self, query):
                return []

            async def download(self, asset, resolution=None):
                return asset

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

    def test_all_plugins_are_registered(self):
        """All plugins should be registered in the registry."""
        from uab import plugins  # noqa: F401
        from uab.plugins import MockPlugin, LocalLibraryPlugin, PolyHavenPlugin

        assert MockPlugin.plugin_id == "mock"
        assert LocalLibraryPlugin.plugin_id == "local"
        assert PolyHavenPlugin.plugin_id == "polyhaven"

    def test_can_instantiate_registered_plugins(self, tmp_path: Path):
        """Should be able to instantiate plugins from registry."""
        from uab.plugins import MockPlugin, LocalLibraryPlugin, PolyHavenPlugin

        db = AssetDatabase(db_path=tmp_path / "test.db")

        mock = MockPlugin()
        assert mock.plugin_id == "mock"

        local = LocalLibraryPlugin(db=db, library_root=tmp_path / "lib")
        assert local.plugin_id == "local"

        polyhaven = PolyHavenPlugin(db=db, library_root=tmp_path / "lib")
        assert polyhaven.plugin_id == "polyhaven"
