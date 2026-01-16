"""Main presenter for Universal Asset Browser.

This is the composition root that coordinates the application:
- Discovers plugins via the PluginRegistry
- Populates the New Tab menu
- Creates and manages TabPresenter instances for each tab
- Routes host integration to tab presenters
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from uab.core.interfaces import AssetLibraryPlugin

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration
    from uab.presenters.tab_presenter import TabPresenter
    from uab.ui.browser import BrowserView
    from uab.ui.main_widget import MainWidget

logger = logging.getLogger(__name__)


class MainPresenter:
    """
    Application shell controller. Basically a simple router for TabPresenters.

    The MainPresenter is the composition root of the application. It:
        - Discovers available plugins via auto-registration
        - Populates the "New Tab" menu with discovered plugins
        - Creates TabPresenter instances when tabs are opened
        - Manages tab lifecycle (creation, closure)

    The presenter is owned by the MainWidget to ensure proper lifetime management
    in embedded contexts like Houdini.

    Args:
        view: The MainWidget instance that owns this presenter
        host: The HostIntegration for the current environment

    Example:
        # Created via MainWidget.initialize()
        widget = MainWidget()
        presenter = widget.initialize(host_integration=HoudiniIntegration())
    """

    def __init__(self, view: MainWidget, host: HostIntegration) -> None:
        self._view = view
        self._host = host

        # Maps tab index to (plugin_id, tab_presenter) tuple
        self._tabs: dict[int, tuple[str, TabPresenter]] = {}

        # Maps plugin_id to instantiated plugin
        self._plugins: dict[str, AssetLibraryPlugin] = {}

        # Initialize
        self._discover_plugins()
        self._setup_connections()
        self._populate_menus()

        # Optionally create a default tab
        self._create_default_tab()

    def _discover_plugins(self) -> None:
        """
        Discover and import all available plugins.

        Plugins auto-register via __init_subclass__ when their modules are imported.
        This method imports all modules in the plugins package to trigger registration.
        """
        try:
            from uab import plugins

            # Import all modules in the plugins package to trigger auto-registration
            for _, name, _ in pkgutil.iter_modules(plugins.__path__):
                try:
                    importlib.import_module(f"uab.plugins.{name}")
                    logger.debug(f"Imported plugin module: {name}")
                except ImportError as e:
                    logger.warning(
                        f"Failed to import plugin module {name}: {e}")
        except ImportError:
            logger.info("Plugins package not found - no plugins loaded")

        # Get all registered plugin classes and instantiate them
        plugin_classes = AssetLibraryPlugin.get_all()
        for plugin_id, plugin_cls in plugin_classes.items():
            try:
                self._plugins[plugin_id] = plugin_cls()
                logger.info(
                    f"Loaded plugin: {plugin_id} ({plugin_cls.display_name})")
            except Exception as e:
                logger.error(f"Failed to instantiate plugin {plugin_id}: {e}")

    def _setup_connections(self) -> None:
        """Connect to view signals."""
        self._view.new_tab_requested.connect(self._on_new_tab_requested)
        self._view.tab_closed.connect(self._on_tab_closed)

    def _populate_menus(self) -> None:
        """Populate the New Tab menu with discovered plugins."""
        plugins_menu = {
            plugin_id: plugin.display_name
            for plugin_id, plugin in self._plugins.items()
        }
        self._view.populate_new_tab_menu(plugins_menu)

    def _create_default_tab(self) -> None:
        """Create a default tab on startup if plugins are available."""
        if not self._plugins:
            logger.info("No plugins available - skipping default tab creation")
            return

        # Prefer "local" plugin if available, otherwise use first plugin
        default_plugin_id = "local" if "local" in self._plugins else next(
            iter(self._plugins))
        self.create_tab(default_plugin_id)

    # -------------
    # Tab Management
    # -------------

    def create_tab(self, plugin_id: str) -> int:
        """
        Create a new tab for the specified plugin.

        Args:
            plugin_id: The plugin ID to create a tab for

        Returns:
            The index of the created tab

        Raises:
            ValueError: If the plugin_id is not found
        """
        if plugin_id not in self._plugins:
            raise ValueError(f"Unknown plugin: {plugin_id}")

        plugin = self._plugins[plugin_id]

        # Create the browser view for this tab
        from uab.ui.browser import BrowserView

        browser_view = BrowserView()

        # Configure the view based on plugin capabilities
        browser_view.set_download_enabled(plugin.can_download)
        browser_view.set_remove_enabled(plugin.can_remove)

        # Set up renderers from host integration
        renderers = self._get_available_renderers()
        browser_view.set_renderers(renderers)

        # Create the tab presenter (will be fully implemented in Phase 3.2)
        tab_presenter = self._create_tab_presenter(plugin, browser_view)

        # Add the tab to the view
        tab_index = self._view.add_tab(browser_view, plugin.display_name)

        # Store the tab info
        self._tabs[tab_index] = (plugin_id, tab_presenter)

        logger.info(
            f"Created tab for plugin: {plugin_id} at index {tab_index}")

        return tab_index

    def close_tab(self, index: int) -> None:
        """
        Close the tab at the given index.

        Args:
            index: The tab index to close
        """
        if index not in self._tabs:
            logger.warning(f"Attempted to close unknown tab index: {index}")
            return

        plugin_id, tab_presenter = self._tabs[index]

        # Clean up the tab presenter
        if tab_presenter is not None:
            self._cleanup_tab_presenter(tab_presenter)

        # Remove from view
        self._view.remove_tab(index)

        # Remove from our tracking
        del self._tabs[index]

        # Re-index remaining tabs (indices shift down after removal)
        self._reindex_tabs(index)

        logger.info(f"Closed tab for plugin: {plugin_id}")

    def _reindex_tabs(self, removed_index: int) -> None:
        """Re-index tabs after a tab removal."""
        new_tabs = {}
        for old_index, tab_info in sorted(self._tabs.items()):
            if old_index > removed_index:
                new_tabs[old_index - 1] = tab_info
            else:
                new_tabs[old_index] = tab_info
        self._tabs = new_tabs

    def _create_tab_presenter(
        self, plugin: AssetLibraryPlugin, view: BrowserView
    ) -> TabPresenter:
        """
        Create a TabPresenter for the given plugin and view.

        Args:
            plugin: The plugin instance
            view: The BrowserView instance

        Returns:
            The TabPresenter instance
        """
        from uab.presenters.tab_presenter import TabPresenter

        tab_presenter = TabPresenter(
            plugin=plugin,
            view=view,
            host=self._host,
        )

        # Connect status messages to main view
        tab_presenter.status_message.connect(self._view.set_status)

        return tab_presenter

    def _cleanup_tab_presenter(self, tab_presenter: TabPresenter) -> None:
        """
        Clean up resources held by a tab presenter.

        Args:
            tab_presenter: The TabPresenter to clean up
        """
        if tab_presenter is None:
            return

        # Cleanup
        if hasattr(tab_presenter, "cleanup"):
            tab_presenter.cleanup()

    # -------------------------------------------------------------------------
    # Host Integration Helpers
    # -------------------------------------------------------------------------

    def _get_available_renderers(self) -> list[str]:
        """Get the list of renderers supported by UAB and available in the host."""
        # Get renderers that UAB supports
        uab_supported = self._host.uab_supported_renderers

        # Get renderers available in the host
        host_available = self._host.get_host_available_renderers()

        # Return intersection, maintaining UAB's preferred order
        return [r for r in uab_supported if r in host_available]

    # -------------------------------------------------------------------------
    # Signal Handlers
    # -------------------------------------------------------------------------

    def _on_new_tab_requested(self, plugin_id: str) -> None:
        """Handle request to create a new tab."""
        try:
            self.create_tab(plugin_id)
        except ValueError as e:
            logger.error(f"Failed to create tab: {e}")
            self._view.set_status(f"Error: {e}")

    def _on_tab_closed(self, index: int) -> None:
        """Handle tab close request."""
        self.close_tab(index)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @property
    def view(self) -> MainWidget:
        """The MainWidget this presenter manages."""
        return self._view

    @property
    def host(self) -> HostIntegration:
        """The host integration for the current environment."""
        return self._host

    @property
    def plugins(self) -> dict[str, AssetLibraryPlugin]:
        """Dictionary of loaded plugins (plugin_id → plugin instance)."""
        return self._plugins.copy()

    @property
    def tab_count(self) -> int:
        """Number of open tabs."""
        return len(self._tabs)

    def get_plugin_for_tab(self, index: int) -> AssetLibraryPlugin | None:
        """
        Get the plugin instance for a tab.

        Args:
            index: The tab index

        Returns:
            The plugin instance, or None if not found
        """
        if index not in self._tabs:
            return None
        plugin_id, _ = self._tabs[index]
        return self._plugins.get(plugin_id)
