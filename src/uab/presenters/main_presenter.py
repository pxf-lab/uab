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
from uab.core.preferences import PreferencesStore, UserPreferences

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration
    from uab.presenters.tab_presenter import TabPresenter
    from uab.ui.browser import BrowserView
    from uab.ui.main_widget import MainWidget
    from uab.ui.settings_tab import SettingsTab

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

    _SETTINGS_TAB_ID = "__settings__"

    def __init__(self, view: MainWidget, host: HostIntegration) -> None:
        self._view = view
        self._host = host

        # Maps tab index to (plugin_id, tab_presenter) tuple.
        # Settings tabs are tracked with tab_presenter=None.
        self._tabs: dict[int, tuple[str, TabPresenter | None]] = {}

        # Maps plugin_id to instantiated plugin
        self._plugins: dict[str, AssetLibraryPlugin] = {}

        # Persistent user preferences (used by settings + quick import defaults)
        self._preferences_store = PreferencesStore()
        self._preferences: UserPreferences = self._preferences_store.load()
        self._settings_tab: SettingsTab | None = None

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
        plugins_menu[self._SETTINGS_TAB_ID] = "Settings"
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

    def _create_settings_tab(self) -> int:
        """Create (or focus) the Settings tab."""
        try:
            from uab.ui.settings_tab import SettingsTab
        except Exception as e:
            logger.warning(f"Failed to import SettingsTab: {e}")
            raise ValueError("Settings tab is unavailable") from e

        try:
            if self._settings_tab is None:
                settings_tab = SettingsTab()
                hdri = self._preferences.hdri_quick_import
                settings_tab.set_hdri_quick_import_preferences(
                    resolution=hdri.resolution,
                    file_type=hdri.file_type,
                )
                settings_tab.hdri_quick_import_changed.connect(
                    self._on_hdri_quick_import_changed
                )
                self._settings_tab = settings_tab
            else:
                settings_tab = self._settings_tab

            add_settings_tab = getattr(self._view, "add_settings_tab", None)
            if callable(add_settings_tab):
                tab_index = add_settings_tab(settings_tab, "Settings")
            else:
                # Backward-compatible fallback for views without add_settings_tab().
                try:
                    tab_index = self._view.add_tab(settings_tab, "Settings", closable=True)
                except TypeError:
                    tab_index = self._view.add_tab(settings_tab, "Settings")

            self._tabs[tab_index] = (self._SETTINGS_TAB_ID, None)
            return tab_index
        except Exception as e:
            logger.warning(f"Failed to create settings tab: {e}")
            raise ValueError("Settings tab could not be created") from e

    def _on_hdri_quick_import_changed(self, resolution: str, file_type: str) -> None:
        """Persist updated HDRI quick-import preferences from the Settings tab."""
        try:
            self._preferences = self._preferences_store.update_hdri_quick_import(
                resolution=resolution,
                file_type=file_type,
            )
            logger.debug(
                "Saved HDRI quick import prefs: resolution=%s, file_type=%s",
                self._preferences.hdri_quick_import.resolution,
                self._preferences.hdri_quick_import.file_type,
            )
        except Exception as e:
            logger.warning(f"Failed to save HDRI quick import settings: {e}")

    def _get_user_preferences(self) -> UserPreferences:
        """Return the latest in-memory user preferences snapshot."""
        return self._preferences

    # TAB MANAGEMENT

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
        if plugin_id == self._SETTINGS_TAB_ID:
            return self._create_settings_tab()

        if plugin_id not in self._plugins:
            raise ValueError(f"Unknown plugin: {plugin_id}")

        plugin = self._plugins[plugin_id]

        from uab.ui.browser import BrowserView

        browser_view = BrowserView()

        # Local Library shows mixed-source items; enable download controls so
        # source-aware delegation can download cloud variants from this tab.
        # TODO: gotta be a better way to do this
        # TODO: review downloadable flag on plugins since local can download now too.
        browser_view.set_download_enabled(
            plugin.can_download or plugin_id == "local")
        browser_view.set_remove_enabled(plugin.can_remove)

        show_import_ui = self._host.supports_import
        browser_view.set_host_import_enabled(show_import_ui)
        browser_view.set_renderer_selector_visible(show_import_ui)

        renderers = self._get_available_renderers()
        browser_view.set_renderers(renderers)

        tab_presenter = self._create_tab_presenter(plugin, browser_view)

        tab_index = self._view.add_tab(browser_view, plugin.display_name)

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

        if tab_presenter is not None:
            self._cleanup_tab_presenter(tab_presenter)

        self._view.remove_tab(index)

        del self._tabs[index]

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
            get_plugin_by_source=self._plugins.get,
            get_user_preferences=self._get_user_preferences,
        )

        tab_presenter.status_message.connect(self._view.set_status)

        tab_presenter.download_complete.connect(self._on_download_complete)

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

    # INTERNAL METHODS

    def _get_available_renderers(self) -> list[str]:
        """Get the list of renderers supported by UAB and available in the host."""
        uab_supported = self._host.uab_supported_renderers

        host_available = self._host.get_host_available_renderers()

        # intersection of renderers supported by UAB and available in the host
        return [r for r in uab_supported if r in host_available]

    # SIGNAL HANDLERS

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

    def _on_download_complete(self, payload: object | None = None) -> None:
        """
        Handle download completion from any tab

        Refreshes any open local library tabs so newly downloaded assets appear.
        """
        # Payload is optional; TabPresenter emits a dict like:
        # {"source": "polyhaven", "downloaded_item_ids": ["..."]}
        source = None
        downloaded_ids: list[str] | None = None
        if isinstance(payload, dict):
            source = payload.get("source")
            maybe_ids = payload.get("downloaded_item_ids")
            if isinstance(maybe_ids, list) and all(isinstance(x, str) for x in maybe_ids):
                downloaded_ids = maybe_ids

        for tab_index, (plugin_id, tab_presenter) in self._tabs.items():
            if plugin_id == "local" and tab_presenter is not None:
                logger.debug(
                    f"Refreshing local library tab at index {tab_index}")
                # In future we can use downloaded_ids to do targeted refresh.
                tab_presenter.refresh()

    # PUBLIC API

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
