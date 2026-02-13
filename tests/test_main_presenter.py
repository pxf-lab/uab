"""Tests for MainPresenter."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
from uab.core.models import StandardAsset, AssetStatus, AssetType


class MockHostIntegration(HostIntegration):
    """Mock host integration for testing."""

    @property
    def uab_supported_renderers(self) -> list[str]:
        return ["arnold", "redshift"]

    def import_asset(self, asset: StandardAsset, options: dict[str, Any]) -> None:
        pass

    def update_selection(self, asset: StandardAsset) -> None:
        pass

    def get_host_available_renderers(self) -> list[str]:
        return ["arnold", "redshift", "karma"]

    def get_active_renderer(self) -> str:
        return "arnold"


class TestPlugin(AssetLibraryPlugin):
    """Test plugin for MainPresenter tests."""

    plugin_id = "test_plugin"
    display_name = "Test Plugin"

    async def search(self, query: str) -> list[StandardAsset]:
        return [
            StandardAsset(
                source=self.plugin_id,
                external_id="test_asset",
                name="Test Asset",
                type=AssetType.HDRI,
                status=AssetStatus.LOCAL,
            )
        ]

    async def download(
        self, asset: StandardAsset, resolution: str | None = None
    ) -> StandardAsset:
        return asset

    @property
    def can_download(self) -> bool:
        return True

    @property
    def can_remove(self) -> bool:
        return False


@pytest.fixture
def mock_view() -> MagicMock:
    """Create a mock MainWidget view."""
    view = MagicMock()
    view.new_tab_requested = MagicMock()
    view.tab_closed = MagicMock()
    view.populate_new_tab_menu = MagicMock()
    view.add_tab = MagicMock(return_value=0)
    view.remove_tab = MagicMock()
    view.set_status = MagicMock()

    # Make signal connections work
    view.new_tab_requested.connect = MagicMock()
    view.tab_closed.connect = MagicMock()

    return view


@pytest.fixture
def mock_host() -> MockHostIntegration:
    """Create a mock host integration."""
    return MockHostIntegration()


@pytest.fixture(autouse=True)
def reset_plugin_registry():
    """Reset the plugin registry before and after each test."""
    # Store original implementations
    original = AssetLibraryPlugin._implementations.copy()

    # Clear and add only our test plugin
    AssetLibraryPlugin.reset_registry()

    yield

    # Restore original implementations
    AssetLibraryPlugin._implementations = original


# TESTS


class TestMainPresenterInit:
    """Tests for MainPresenter initialization."""

    def test_presenter_stores_view_and_host(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should store references to view and host."""
        # Register test plugin
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView"):
            from uab.presenters.main_presenter import MainPresenter

            presenter = MainPresenter(view=mock_view, host=mock_host)

            assert presenter.view is mock_view
            assert presenter.host is mock_host

    def test_presenter_connects_to_view_signals(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should connect to view signals."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView"):
            from uab.presenters.main_presenter import MainPresenter

            MainPresenter(view=mock_view, host=mock_host)

            mock_view.new_tab_requested.connect.assert_called_once()
            mock_view.tab_closed.connect.assert_called_once()

    def test_presenter_populates_menu_from_plugins(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should populate the New Tab menu with discovered plugins."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView"):
            from uab.presenters.main_presenter import MainPresenter

            MainPresenter(view=mock_view, host=mock_host)

            mock_view.populate_new_tab_menu.assert_called_once()
            call_args = mock_view.populate_new_tab_menu.call_args[0][0]
            assert "test_plugin" in call_args
            assert call_args["test_plugin"] == "Test Plugin"


class TestMainPresenterPluginDiscovery:
    """Tests for plugin discovery."""

    def test_plugins_property_returns_loaded_plugins(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """The plugins property should return discovered plugin instances."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView"):
            from uab.presenters.main_presenter import MainPresenter

            presenter = MainPresenter(view=mock_view, host=mock_host)

            plugins = presenter.plugins
            assert "test_plugin" in plugins
            assert isinstance(plugins["test_plugin"], TestPlugin)

    def test_presenter_handles_no_plugins_gracefully(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Presenter should handle having no plugins without error."""
        # Don't register any plugins
        from uab.presenters.main_presenter import MainPresenter

        presenter = MainPresenter(view=mock_view, host=mock_host)

        assert presenter.plugins == {}
        assert presenter.tab_count == 0


class TestMainPresenterTabManagement:
    """Tests for tab creation and management."""

    def test_create_tab_returns_tab_index(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """create_tab should return the new tab's index."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin
        mock_view.add_tab.return_value = 0

        with patch("uab.ui.browser.BrowserView") as mock_browser:
            mock_browser.return_value = MagicMock()
            from uab.presenters.main_presenter import MainPresenter

            # Don't create default tab to control tab creation
            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            index = presenter.create_tab("test_plugin")

            assert index == 0

    def test_create_tab_adds_widget_to_view(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """create_tab should add a BrowserView to the MainWidget."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView") as mock_browser:
            mock_browser_instance = MagicMock()
            mock_browser.return_value = mock_browser_instance

            from uab.presenters.main_presenter import MainPresenter

            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            presenter.create_tab("test_plugin")

            mock_view.add_tab.assert_called_with(
                mock_browser_instance, "Test Plugin"
            )

    def test_create_tab_unknown_plugin_raises_error(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """create_tab should raise ValueError for unknown plugins."""
        from uab.presenters.main_presenter import MainPresenter

        presenter = MainPresenter(view=mock_view, host=mock_host)

        with pytest.raises(ValueError, match="Unknown plugin"):
            presenter.create_tab("nonexistent_plugin")

    def test_close_tab_removes_tab_from_view(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """close_tab should remove the tab from the view."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin
        mock_view.add_tab.return_value = 0

        with patch("uab.ui.browser.BrowserView") as mock_browser:
            mock_browser.return_value = MagicMock()
            from uab.presenters.main_presenter import MainPresenter

            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            presenter.create_tab("test_plugin")
            presenter.close_tab(0)

            mock_view.remove_tab.assert_called_with(0)

    def test_tab_count_property(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """tab_count should reflect the number of open tabs."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView") as mock_browser:
            mock_browser.return_value = MagicMock()
            from uab.presenters.main_presenter import MainPresenter

            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            assert presenter.tab_count == 0

            mock_view.add_tab.return_value = 0
            presenter.create_tab("test_plugin")
            assert presenter.tab_count == 1

            mock_view.add_tab.return_value = 1
            presenter.create_tab("test_plugin")
            assert presenter.tab_count == 2

            presenter.close_tab(0)
            assert presenter.tab_count == 1

    def test_create_tab_passes_source_plugin_resolver_to_tab_presenter(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """TabPresenter should receive source->plugin resolver from MainPresenter."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin

        with patch("uab.ui.browser.BrowserView") as mock_browser, patch(
            "uab.presenters.tab_presenter.TabPresenter"
        ) as mock_tab_presenter:
            mock_browser_instance = MagicMock()
            mock_browser.return_value = mock_browser_instance

            tab_presenter_instance = MagicMock()
            mock_tab_presenter.return_value = tab_presenter_instance

            from uab.presenters.main_presenter import MainPresenter

            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            presenter.create_tab("test_plugin")

            kwargs = mock_tab_presenter.call_args.kwargs
            resolver = kwargs.get("get_plugin_by_source")
            assert callable(resolver)

            plugin = presenter.plugins["test_plugin"]
            assert resolver("test_plugin") is plugin
            assert resolver("missing_plugin") is None


class TestMainPresenterRenderers:
    """Tests for renderer handling."""

    def test_available_renderers_is_intersection(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """Available renderers should be intersection of UAB and host support."""
        from uab.presenters.main_presenter import MainPresenter

        presenter = MainPresenter(view=mock_view, host=mock_host)

        # MockHostIntegration:
        # - uab_supported: ["arnold", "redshift"]
        # - host_available: ["arnold", "redshift", "karma"]
        # Intersection: ["arnold", "redshift"]
        renderers = presenter._get_available_renderers()

        assert renderers == ["arnold", "redshift"]


class TestMainPresenterCrossTabRefresh:
    def test_download_complete_refreshes_local_tabs(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """When a download completes, local library tabs should refresh."""
        from uab.presenters.main_presenter import MainPresenter

        with patch.object(MainPresenter, "_create_default_tab"):
            presenter = MainPresenter(view=mock_view, host=mock_host)

        local_tab = MagicMock()
        other_tab = MagicMock()
        presenter._tabs = {0: ("local", local_tab), 1: ("polyhaven", other_tab)}

        presenter._on_download_complete(
            {"source": "polyhaven", "downloaded_item_ids": ["asset-1"]}
        )

        local_tab.refresh.assert_called_once()


class TestMainPresenterGetPluginForTab:
    """Tests for get_plugin_for_tab method."""

    def test_get_plugin_for_existing_tab(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """get_plugin_for_tab should return the plugin for an existing tab."""
        AssetLibraryPlugin._implementations["test_plugin"] = TestPlugin
        mock_view.add_tab.return_value = 0

        with patch("uab.ui.browser.BrowserView") as mock_browser:
            mock_browser.return_value = MagicMock()
            from uab.presenters.main_presenter import MainPresenter

            with patch.object(MainPresenter, "_create_default_tab"):
                presenter = MainPresenter(view=mock_view, host=mock_host)

            presenter.create_tab("test_plugin")

            plugin = presenter.get_plugin_for_tab(0)
            assert isinstance(plugin, TestPlugin)

    def test_get_plugin_for_nonexistent_tab(
        self, mock_view: MagicMock, mock_host: MockHostIntegration
    ) -> None:
        """get_plugin_for_tab should return None for nonexistent tabs."""
        from uab.presenters.main_presenter import MainPresenter

        presenter = MainPresenter(view=mock_view, host=mock_host)

        plugin = presenter.get_plugin_for_tab(999)
        assert plugin is None
