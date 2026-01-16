"""Tab presenter for Universal Asset Browser.

Each tab in the browser has its own TabPresenter that coordinates
between the plugin (data source) and the BrowserView (UI).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QDialogButtonBox,
    QMessageBox,
)

from uab.core.models import StandardAsset, AssetStatus

if TYPE_CHECKING:
    from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
    from uab.ui.browser import BrowserView

logger = logging.getLogger(__name__)


class TabPresenter(QObject):
    """
    Presenter for a single browser tab.

    Coordinates between an AssetLibraryPlugin (data source) and a
    BrowserView. Handles:
        - Async search with task cancellation
        - Asset detail viewing
        - Download flow with progress
        - Import flow with settings dialog

    Args:
        plugin: The asset library plugin for this tab
        view: The BrowserView widget
        host: The host integration for imports

    Signals:
        status_message: Emitted when there's a status update for the main window
    """

    status_message = Signal(str)  # Message to display in status bar

    def __init__(
        self,
        plugin: AssetLibraryPlugin,
        view: BrowserView,
        host: HostIntegration,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._plugin = plugin
        self._view = view
        self._host = host

        self._current_task: asyncio.Task | None = None

        self._asset_cache: dict[str, StandardAsset] = {}

        self._is_loading = False

        self._setup_connections()
        self._trigger_initial_search()

    def _setup_connections(self) -> None:
        """Connect to view signals."""
        self._view.search_requested.connect(self._on_search_requested)
        self._view.detail_requested.connect(self._on_detail_requested)
        self._view.import_requested.connect(self._on_import_requested)
        self._view.download_requested.connect(self._on_download_requested)
        self._view.remove_requested.connect(self._on_remove_requested)

    def _trigger_initial_search(self) -> None:
        """Trigger an initial empty search to populate the view."""
        # Use a timer to ensure this runs after the event loop starts
        QTimer.singleShot(0, lambda: self._on_search_requested(""))

    # -------------
    # Async Helpers
    # -------------

    def _run_async(self, coro) -> asyncio.Task | None:
        """
        Run an async coroutine, handling event loop setup.

        # TODO: Use qasync for event loop management
        """
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
                return None
            except Exception as e:
                logger.error(f"Failed to run async task: {e}")
                return None

    async def _cancel_current_task(self) -> None:
        """Cancel the current async task if running."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            self._current_task = None

    # -----------
    # Search Flow
    # -----------

    @Slot(str)
    def _on_search_requested(self, query: str) -> None:
        """Handle search request from view."""
        logger.debug(f"Search requested: '{query}'")
        self._run_async(self._do_search(query))

    async def _do_search(self, query: str) -> None:
        """Execute search asynchronously."""
        # Cancel any pending search
        await self._cancel_current_task()

        # Set loading state
        self._is_loading = True
        self._view.set_loading(True)

        try:
            # Execute search
            assets = await self._plugin.search(query)

            # Update cache
            self._asset_cache.clear()
            for asset in assets:
                self._asset_cache[asset.id] = asset

            # Update view
            self._view.set_items(assets)

            logger.info(f"Search complete: {len(assets)} assets found")
            self.status_message.emit(f"Found {len(assets)} assets")

        except asyncio.CancelledError:
            logger.debug("Search cancelled")
            raise
        except Exception as e:
            logger.error(f"Search failed: {e}")
            self.status_message.emit(f"Search failed: {e}")
            self._view.set_items([])
        finally:
            self._is_loading = False
            self._view.set_loading(False)

    @Slot(str)
    def _on_detail_requested(self, asset_id: str) -> None:
        """Handle detail view request."""
        asset = self._asset_cache.get(asset_id)
        if asset:
            self._view.show_detail(asset)
        else:
            logger.warning(f"Asset not found in cache: {asset_id}")

    @Slot(str)
    def _on_import_requested(self, asset_id: str) -> None:
        """Handle import request."""
        asset = self._asset_cache.get(asset_id)
        if not asset:
            logger.warning(f"Asset not found for import: {asset_id}")
            return

        self._run_async(self._do_import(asset))

    async def _do_import(self, asset: StandardAsset) -> None:
        """Execute import asynchronously."""
        try:
            # If cloud asset, download first
            if asset.status == AssetStatus.CLOUD:
                self.status_message.emit(f"Downloading {asset.name}...")
                asset = await self._do_download_for_import(asset)
                if asset.status != AssetStatus.LOCAL:
                    self.status_message.emit(
                        "Download failed, import cancelled")
                    return

            # Check for settings schema
            schema = self._plugin.get_settings_schema(asset)
            options: dict[str, Any] = {}

            if schema:
                # Show settings dialog
                options = self._show_settings_dialog(schema, asset)
                if options is None:
                    # User cancelled
                    logger.info("Import cancelled by user")
                    return

            # Add selected renderer to options
            options["renderer"] = self._view.get_selected_renderer()

            # Execute import
            self.status_message.emit(f"Importing {asset.name}...")
            self._host.import_asset(asset, options)
            self.status_message.emit(f"Imported {asset.name}")

        except Exception as e:
            logger.error(f"Import failed: {e}")
            self.status_message.emit(f"Import failed: {e}")

    async def _do_download_for_import(self, asset: StandardAsset) -> StandardAsset:
        """Download an asset as part of import flow."""
        try:
            # TODO: Make resolution configurable
            resolution = "2k"

            updated_asset = await self._plugin.download(asset, resolution)

            self._asset_cache[updated_asset.id] = updated_asset

            return updated_asset
        except Exception as e:
            logger.error(f"Download for import failed: {e}")
            return asset

    def _show_settings_dialog(
        self, schema: dict[str, Any], asset: StandardAsset
    ) -> dict[str, Any] | None:
        """
        Show settings dialog based on schema.

        Args:
            schema: Settings schema from plugin
            asset: The asset being imported

        Returns:
            Dict of settings values, or None if cancelled
        """
        dialog = QDialog(self._view)
        dialog.setWindowTitle(f"Import Settings - {asset.name}")
        dialog.setMinimumWidth(300)

        layout = QFormLayout(dialog)
        widgets: dict[str, QComboBox | QLineEdit | QCheckBox] = {}

        for key, config in schema.items():
            field_type = config.get("type", "text")
            default = config.get("default", "")

            if field_type == "choice":
                widget = QComboBox()
                options = config.get("options", [])
                widget.addItems(options)
                if default in options:
                    widget.setCurrentText(default)
                widgets[key] = widget

            elif field_type == "bool":
                widget = QCheckBox()
                widget.setChecked(bool(default))
                widgets[key] = widget

            else:
                widget = QLineEdit()
                widget.setText(str(default))
                widgets[key] = widget

            label = key.replace("_", " ").title()
            layout.addRow(label, widget)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = {}
            for key, widget in widgets.items():
                if isinstance(widget, QComboBox):
                    result[key] = widget.currentText()
                elif isinstance(widget, QCheckBox):
                    result[key] = widget.isChecked()
                else:
                    result[key] = widget.text()
            return result

        return None

    @Slot(str)
    def _on_download_requested(self, asset_id: str) -> None:
        """Handle download request."""
        asset = self._asset_cache.get(asset_id)
        if not asset:
            logger.warning(f"Asset not found for download: {asset_id}")
            return

        if asset.status != AssetStatus.CLOUD:
            logger.info(f"Asset {asset_id} is not a cloud asset")
            return

        self._run_async(self._do_download(asset))

    async def _do_download(self, asset: StandardAsset) -> None:
        """Execute download asynchronously."""
        original_status = asset.status

        try:
            # Update status to downloading
            asset.status = AssetStatus.DOWNLOADING
            self._refresh_asset_in_view(asset)
            self._view.set_download_progress(asset.id, 0.0)

            self.status_message.emit(f"Downloading {asset.name}...")

            # Execute download
            # TODO: Add progress callback support to plugin.download()
            resolution = "2k"  # Default resolution
            updated_asset = await self._plugin.download(asset, resolution)

            # Update cache and view
            self._asset_cache[updated_asset.id] = updated_asset
            self._refresh_asset_in_view(updated_asset)
            self._view.set_download_progress(asset.id, 1.0)

            self.status_message.emit(f"Downloaded {asset.name}")
            logger.info(f"Download complete: {asset.name}")

        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.status_message.emit(f"Download failed: {e}")

            asset.status = original_status
            self._refresh_asset_in_view(asset)
            self._view.set_download_progress(asset.id, -1)

    @Slot(str)
    def _on_remove_requested(self, asset_id: str) -> None:
        """Handle remove request."""
        asset = self._asset_cache.get(asset_id)
        if not asset:
            logger.warning(f"Asset not found for removal: {asset_id}")
            return

        if not self._plugin.can_remove:
            logger.info("Plugin does not support removal")
            return

        # Double check
        reply = QMessageBox.question(
            self._view,
            "Remove Asset",
            f"Remove '{asset.name}' from the library?\n\n"
            "This will delete the local files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._run_async(self._do_remove(asset))

    async def _do_remove(self, asset: StandardAsset) -> None:
        """Execute removal asynchronously."""
        try:
            # TODO: Call plugin.remove() when available
            if asset.id in self._asset_cache:
                del self._asset_cache[asset.id]

            # Refresh the view
            self._view.set_items(list(self._asset_cache.values()))
            self.status_message.emit(f"Removed {asset.name}")

        except Exception as e:
            logger.error(f"Remove failed: {e}")
            self.status_message.emit(f"Remove failed: {e}")

    def _refresh_asset_in_view(self, asset: StandardAsset) -> None:
        """Refresh a single asset in the view."""
        # For now, refresh entire list - could be optimized
        self._view.set_items(list(self._asset_cache.values()))

    # PUBLIC API

    @property
    def plugin(self) -> AssetLibraryPlugin:
        """The plugin for this tab."""
        return self._plugin

    @property
    def view(self) -> BrowserView:
        """The view for this tab."""
        return self._view

    @property
    def is_loading(self) -> bool:
        """Whether the tab is currently loading."""
        return self._is_loading

    def cleanup(self) -> None:
        """Clean up resources when tab is closed."""
        # Cancel any pending task
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

        # Clear cache
        self._asset_cache.clear()

        logger.debug(
            f"TabPresenter cleaned up for plugin: {self._plugin.plugin_id}")
