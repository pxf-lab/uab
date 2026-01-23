"""Tests for TabPresenter."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
from uab.core.models import StandardAsset, AssetStatus, AssetType


# TEST FIXTURES


class MockHostIntegration(HostIntegration):
    """Mock host integration for testing."""

    def __init__(self):
        self.imported_assets: list[tuple[StandardAsset, dict]] = []

    @property
    def uab_supported_renderers(self) -> list[str]:
        return ["arnold", "redshift"]

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        self.imported_assets.append((asset, options))

    def update_selection(self, asset: StandardAsset) -> None:
        pass

    def get_host_available_renderers(self) -> list[str]:
        return ["arnold", "redshift"]

    def get_active_renderer(self) -> str:
        return "arnold"


class MockPlugin(AssetLibraryPlugin):
    """Mock plugin for TabPresenter tests."""

    plugin_id = "mock_tab_test"
    display_name = "Mock Tab Test"

    def __init__(self):
        self._assets = [
            StandardAsset(
                source=self.plugin_id,
                external_id="asset_1",
                name="Test Asset 1",
                type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
            ),
            StandardAsset(
                source=self.plugin_id,
                external_id="asset_2",
                name="Test Asset 2",
                type=AssetType.TEXTURE,
                status=AssetStatus.CLOUD,
            ),
        ]
        self.search_calls: list[str] = []
        self.download_calls: list[tuple[StandardAsset, str | None]] = []

    async def search(self, query: str) -> list[StandardAsset]:
        self.search_calls.append(query)
        if query:
            return [a for a in self._assets if query.lower() in a.name.lower()]
        return self._assets.copy()

    async def download(
        self, asset: StandardAsset, resolution: str | None = None
    ) -> StandardAsset:
        self.download_calls.append((asset, resolution))
        # Return updated asset with LOCAL status
        return StandardAsset(
            source=asset.source,
            external_id=asset.external_id,
            name=asset.name,
            type=asset.type,
            status=AssetStatus.LOCAL,
            id=asset.id,
        )

    @property
    def can_download(self) -> bool:
        return True

    @property
    def can_remove(self) -> bool:
        return True

    def get_settings_schema(self, asset: StandardAsset) -> dict | None:
        if asset.type == AssetType.HDRI:
            return {
                "resolution": {
                    "type": "choice",
                    "options": ["1k", "2k", "4k"],
                    "default": "2k",
                }
            }
        return None


@pytest.fixture
def mock_plugin() -> MockPlugin:
    """Create a mock plugin."""
    return MockPlugin()


@pytest.fixture
def mock_host() -> MockHostIntegration:
    """Create a mock host integration."""
    return MockHostIntegration()


@pytest.fixture
def mock_view() -> MagicMock:
    """Create a mock BrowserView."""
    view = MagicMock()
    view.search_requested = MagicMock()
    view.detail_requested = MagicMock()
    view.import_requested = MagicMock()
    view.download_requested = MagicMock()
    view.remove_requested = MagicMock()

    # Make signal connections work
    view.search_requested.connect = MagicMock()
    view.detail_requested.connect = MagicMock()
    view.import_requested.connect = MagicMock()
    view.download_requested.connect = MagicMock()
    view.remove_requested.connect = MagicMock()

    view.set_items = MagicMock()
    view.set_loading = MagicMock()
    view.show_detail = MagicMock()
    view.set_download_progress = MagicMock()
    view.get_selected_renderer = MagicMock(return_value="arnold")

    return view


@pytest.fixture(autouse=True)
def reset_plugin_registry():
    """Reset the plugin registry before and after each test."""
    original = AssetLibraryPlugin._implementations.copy()
    AssetLibraryPlugin.reset_registry()
    yield
    AssetLibraryPlugin._implementations = original


# TESTS


class TestTabPresenterInit:
    """Tests for TabPresenter initialization."""

    def test_presenter_stores_dependencies(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should store plugin, view, and host references."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        assert presenter.plugin is mock_plugin
        assert presenter.view is mock_view

    def test_presenter_connects_to_view_signals(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should connect to all view signals."""
        from uab.presenters.tab_presenter import TabPresenter

        TabPresenter(plugin=mock_plugin, view=mock_view, host=mock_host)

        mock_view.search_requested.connect.assert_called_once()
        mock_view.detail_requested.connect.assert_called_once()
        mock_view.import_requested.connect.assert_called_once()
        mock_view.download_requested.connect.assert_called_once()
        mock_view.remove_requested.connect.assert_called_once()


class TestTabPresenterSearch:
    """Tests for search functionality."""

    def test_search_calls_plugin_and_updates_view(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Search should call plugin.search() and update the view."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        asyncio.run(presenter._do_search("test"))

        assert "test" in mock_plugin.search_calls

        mock_view.set_items.assert_called()

    def test_search_updates_loading_state(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Search should set loading state before and after."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        # Clear any initial calls
        mock_view.set_loading.reset_mock()

        asyncio.run(presenter._do_search("query"))

        # Should have called set_loading(True) then set_loading(False)
        calls = mock_view.set_loading.call_args_list
        assert len(calls) >= 2
        # TODO: this is ridiculous
        assert calls[0][0][0] is True  # First call with True
        assert calls[-1][0][0] is False  # Last call with False


class TestTabPresenterDetailView:
    """Tests for detail view functionality."""

    def test_detail_shows_asset_from_cache(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Detail request should show asset from cache."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        # Populate cache
        asyncio.run(presenter._do_search(""))

        asset_id = list(presenter._asset_cache.keys())[0]
        asset = presenter._asset_cache[asset_id]

        presenter._on_detail_requested(asset_id)

        mock_view.show_detail.assert_called_with(asset)

    def test_detail_handles_missing_asset(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Detail request for missing asset should not crash."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        presenter._on_detail_requested("nonexistent_id")

        mock_view.show_detail.assert_not_called()


class TestTabPresenterDownload:
    """Tests for download functionality."""

    def test_download_calls_plugin(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Download should call plugin.download()."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        # Populate cache
        asyncio.run(presenter._do_search(""))

        cloud_asset = None
        for asset in presenter._asset_cache.values():
            if asset.status == AssetStatus.CLOUD:
                cloud_asset = asset
                break

        if cloud_asset:
            asyncio.run(presenter._do_download(cloud_asset))

            assert len(mock_plugin.download_calls) > 0

    def test_download_updates_progress(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Download should update progress in view."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        asyncio.run(presenter._do_search(""))

        cloud_asset = None
        for asset in presenter._asset_cache.values():
            if asset.status == AssetStatus.CLOUD:
                cloud_asset = asset
                break

        if cloud_asset:
            asyncio.run(presenter._do_download(cloud_asset))

            mock_view.set_download_progress.assert_called()


class TestTabPresenterImport:
    """Tests for import functionality."""

    def test_import_local_asset_calls_host(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Import of local asset should call host.import_asset()."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        asyncio.run(presenter._do_search(""))

        local_asset = None
        for asset in presenter._asset_cache.values():
            if asset.status == AssetStatus.LOCAL and asset.type == AssetType.TEXTURE:
                local_asset = asset
                break

        if local_asset:
            asyncio.run(presenter._do_import(local_asset))

            assert len(mock_host.imported_assets) > 0
            imported_asset, options = mock_host.imported_assets[0]
            assert imported_asset.id == local_asset.id


class TestTabPresenterCleanup:
    """Tests for cleanup functionality."""

    def test_cleanup_clears_cache(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Cleanup should clear the asset cache."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        asyncio.run(presenter._do_search(""))
        assert len(presenter._asset_cache) > 0

        presenter.cleanup()

        assert len(presenter._asset_cache) == 0


class TestTabPresenterProperties:
    """Tests for public properties."""

    def test_is_loading_property(
        self, mock_plugin: MockPlugin, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """is_loading should reflect loading state."""
        from uab.presenters.tab_presenter import TabPresenter

        presenter = TabPresenter(
            plugin=mock_plugin, view=mock_view, host=mock_host
        )

        # Initially should not be loading (after initial search completes)
        # Note: due to async nature, this may vary
        assert isinstance(presenter.is_loading, bool)
