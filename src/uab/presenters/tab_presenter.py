"""Tab presenter for Universal Asset Browser.

Each tab in the browser has its own TabPresenter that coordinates
between the plugin (data source) and the BrowserView (UI).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread, QMutex
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QDialogButtonBox,
    QMessageBox,
)

from uab.core.models import StandardAsset, AssetStatus

if TYPE_CHECKING:
    from pathlib import Path
    from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
    from uab.ui.browser import BrowserView

from uab.core.interfaces import SupportsLocalImport

logger = logging.getLogger(__name__)


def get_thumbnail_cache_path(asset: StandardAsset, plugin_id: str) -> "Path":
    """
    Get the cache path for an asset's thumbnail.

    This is a standalone function so it can be used both for checking
    if a thumbnail exists and for saving new thumbnails.

    Args:
        asset: The asset to get cache path for
        plugin_id: The plugin ID for the cache subdirectory

    Returns:
        Path where the thumbnail should be cached
    """
    from pathlib import Path as PathLib
    from uab.core import config

    cache_dir = config.get_thumbnail_cache_dir(plugin_id)

    ext = ".jpg"  # Default thumbnail extension, below hcecks for a different extension from the query
    if asset.thumbnail_url:
        url_path = asset.thumbnail_url.split('?')[0]
        url_ext = PathLib(url_path).suffix.lower()
        if url_ext:
            ext = url_ext

    cache_filename = f"{asset.external_id}{ext}"
    return cache_dir / cache_filename


class ThumbnailWorker(QThread):
    """
    Background worker thread for fetching thumbnails.

    Emits signals when thumbnails are ready so the main thread can
    update the UI safely.

    Uses synchronous HTTP requests (urllib) instead of aiohttp because
    aiohttp sessions are not thread-safe and can't be shared across threads.
    """

    # Emitted when a single thumbnail is fetched: (asset_id, thumbnail_path)
    thumbnail_ready = Signal(str, object)  # asset_id, Path or None

    # Emitted when a batch is complete (for periodic UI updates)
    batch_complete = Signal()

    # Emitted when all thumbnails are done
    all_complete = Signal()

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._plugin_id = plugin.plugin_id
        self._queue: list[StandardAsset] = []
        self._mutex = QMutex()
        self._stop_requested = False
        self._batch_size = 5

    def set_assets(self, assets: list[StandardAsset]) -> None:
        """Set the assets to fetch thumbnails for."""
        self._mutex.lock()
        self._queue = assets.copy()
        self._stop_requested = False
        self._mutex.unlock()

    def request_stop(self) -> None:
        """Request the worker to stop after current download."""
        self._mutex.lock()
        self._stop_requested = True
        self._queue.clear()
        self._mutex.unlock()

    def run(self) -> None:
        """Worker thread main loop."""
        count = 0

        while True:
            # Get next asset from queue
            self._mutex.lock()
            if self._stop_requested or not self._queue:
                self._mutex.unlock()
                break
            asset = self._queue.pop(0)
            self._mutex.unlock()

            thumb_path = self._fetch_thumbnail_sync(asset)

            self.thumbnail_ready.emit(asset.id, thumb_path)
            count += 1

            if count % self._batch_size == 0:
                self.batch_complete.emit()

        self.all_complete.emit()

    def _fetch_thumbnail_sync(self, asset: StandardAsset) -> "Path | None":
        """
        Fetch a single thumbnail using synchronous HTTP (urllib).

        This avoids aiohttp thread-safety issues by using stdlib urllib.
        """
        import urllib.request  # use instead of requests to minimize dependencies
        import urllib.error

        thumbnail_url = asset.thumbnail_url
        if not thumbnail_url:
            return None

        cache_path = get_thumbnail_cache_path(asset, self._plugin_id)

        if cache_path.exists():
            return cache_path

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            request = urllib.request.Request(
                thumbnail_url,
                headers={"User-Agent": "UAB/1.0"}
            )

            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()

            with open(cache_path, "wb") as f:
                f.write(data)

            logger.debug(f"Downloaded thumbnail for {asset.name}")
            return cache_path

        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            logger.debug(f"Failed to fetch thumbnail for {asset.name}: {e}")
            return None
        except Exception as e:
            logger.debug(
                f"Unexpected error fetching thumbnail for {asset.name}: {e}")
            return None


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
        download_complete: Emitted when an asset download completes successfully
    """

    status_message = Signal(str)  # Message to display in status bar
    download_complete = Signal()  # Emitted after successful download

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

        self._current_query: str = ""

        self._thumbnail_worker: ThumbnailWorker | None = None

        self._setup_connections()

        # Configure host-specific context menu actions
        self._view.set_host_actions(
            replace_enabled=self._host.supports_replace_selection,
            get_label=self._host.get_node_label_for_asset_type,
        )

        # Handle local asset library tab
        if isinstance(plugin, SupportsLocalImport):
            self._view.set_add_assets_enabled(True)
            self._view.add_files_requested.connect(
                self._on_add_files_requested)
            self._view.add_folder_requested.connect(
                self._on_add_folder_requested)

        self._trigger_initial_search()

    def _setup_connections(self) -> None:
        """Connect to view signals."""
        self._view.search_requested.connect(self._on_search_requested)
        self._view.detail_requested.connect(self._on_detail_requested)
        self._view.import_requested.connect(self._on_import_requested)
        self._view.download_requested.connect(self._on_download_requested)
        self._view.remove_requested.connect(self._on_remove_requested)
        self._view.new_asset_requested.connect(self._on_new_asset_requested)
        self._view.replace_asset_requested.connect(
            self._on_replace_asset_requested)

    def _trigger_initial_search(self) -> None:
        """Trigger an initial empty search to populate the view."""
        QTimer.singleShot(0, lambda: self._on_search_requested(""))

    # ASYNC HELPERS

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

    # SEARCH FLOW

    @Slot(str)
    def _on_search_requested(self, query: str) -> None:
        """Handle search request from view."""
        logger.debug(f"Search requested: '{query}'")
        self._current_query = query
        self._run_async(self._do_search(query))

    async def _do_search(self, query: str) -> None:
        """Execute search asynchronously."""
        await self._cancel_current_task()

        self._is_loading = True
        self._view.set_loading(True)

        try:
            assets = await self._plugin.search(query)

            self._asset_cache.clear()
            for asset in assets:
                self._asset_cache[asset.id] = asset

            self._view.set_items(assets)

            logger.info(f"Search complete: {len(assets)} assets found")
            self.status_message.emit(f"Found {len(assets)} assets")

            self._queue_thumbnail_fetch(assets)

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

    def _queue_thumbnail_fetch(self, assets: list[StandardAsset]) -> None:
        """
        Queue thumbnails for background fetching using a worker thread.

        First checks for already-cached thumbnails on disk and uses those directly.
        Only queues assets that actually need to be downloaded.
        """
        plugin_id = self._plugin.plugin_id
        assets_needing_download: list[StandardAsset] = []
        cached_count = 0

        for asset in assets:
            if not asset.thumbnail_url:
                continue

            if asset.thumbnail_path and asset.thumbnail_path.exists():
                continue

            cache_path = get_thumbnail_cache_path(asset, plugin_id)
            if cache_path.exists():
                asset.thumbnail_path = cache_path
                self._asset_cache[asset.id] = asset
                cached_count += 1
            else:
                assets_needing_download.append(asset)

        if cached_count > 0:
            logger.debug(f"Found {cached_count} cached thumbnails on disk")
            self._view.set_items(list(self._asset_cache.values()))

        if not assets_needing_download:
            logger.debug("All thumbnails already cached")
            return

        if not hasattr(self._plugin, "download_thumbnail"):
            logger.debug("Plugin does not support thumbnail downloading")
            return

        logger.debug(
            f"Queueing {len(assets_needing_download)} thumbnails for download")

        if self._thumbnail_worker is not None:
            self._thumbnail_worker.request_stop()
            self._thumbnail_worker.wait(1000)  # Wait up to 1 second
            self._thumbnail_worker.deleteLater()

        self._thumbnail_worker = ThumbnailWorker(self._plugin, self)
        self._thumbnail_worker.thumbnail_ready.connect(
            self._on_thumbnail_ready)
        self._thumbnail_worker.batch_complete.connect(
            self._on_thumbnail_batch_complete)
        self._thumbnail_worker.all_complete.connect(
            self._on_thumbnails_complete)
        self._thumbnail_worker.set_assets(assets_needing_download)
        self._thumbnail_worker.start()

    @Slot(str, object)
    def _on_thumbnail_ready(self, asset_id: str, thumb_path) -> None:
        """Handle a thumbnail being ready (called on main thread via signal)."""
        if thumb_path and asset_id in self._asset_cache:
            asset = self._asset_cache[asset_id]
            asset.thumbnail_path = thumb_path
            self._asset_cache[asset_id] = asset

    @Slot()
    def _on_thumbnail_batch_complete(self) -> None:
        """Handle a batch of thumbnails being complete - update the view."""
        self._view.set_items(list(self._asset_cache.values()))

    @Slot()
    def _on_thumbnails_complete(self) -> None:
        """Handle all thumbnails being complete - final view update."""
        self._view.set_items(list(self._asset_cache.values()))
        logger.debug("All thumbnails fetched")

    # Keep async versions for compatibility with code that uses qasync
    async def _fetch_thumbnails(self, assets: list[StandardAsset]) -> None:
        """Fetch thumbnails for assets that have URLs but no local path."""
        assets_needing_thumbs = [
            a for a in assets
            if a.thumbnail_url and (not a.thumbnail_path or not a.thumbnail_path.exists())
        ]

        if not assets_needing_thumbs:
            return

        logger.debug(f"Fetching {len(assets_needing_thumbs)} thumbnails")

        if not hasattr(self._plugin, "download_thumbnail"):
            logger.debug("Plugin does not support thumbnail downloading")
            return

        batch_size = 10
        for i in range(0, len(assets_needing_thumbs), batch_size):
            batch = assets_needing_thumbs[i:i + batch_size]
            tasks = []
            for asset in batch:
                tasks.append(self._fetch_single_thumbnail(asset))

            await asyncio.gather(*tasks, return_exceptions=True)
            self._view.set_items(list(self._asset_cache.values()))

    async def _fetch_single_thumbnail(self, asset: StandardAsset) -> None:
        """Fetch thumbnail for a single asset."""
        try:
            thumb_path = await self._plugin.download_thumbnail(asset)
            if thumb_path:
                asset.thumbnail_path = thumb_path
                self._asset_cache[asset.id] = asset
                logger.debug(f"Thumbnail fetched for {asset.name}")
        except Exception as e:
            logger.debug(f"Failed to fetch thumbnail for {asset.name}: {e}")

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

    @Slot(str)
    def _on_new_asset_requested(self, asset_id: str) -> None:
        """
        Handle new asset request (Cmd/Ctrl+Click in context menu).

        Creates a new node for the asset. This is functionally the same
        as import but with explicit naming for the context menu action.
        """
        self._on_import_requested(asset_id)

    @Slot(str)
    def _on_replace_asset_requested(self, asset_id: str) -> None:
        """
        Handle replace asset request (Opt/Alt+Click in context menu).

        Updates the currently selected node with the new asset data.
        Only available in hosts that support node selection (e.g., Houdini).
        """
        asset = self._asset_cache.get(asset_id)
        if not asset:
            logger.warning(f"Asset not found for replace: {asset_id}")
            return

        try:
            self.status_message.emit(f"Replacing with {asset.name}...")
            self._host.update_selection(asset)
            self.status_message.emit(f"Replaced with {asset.name}")
        except Exception as e:
            logger.error(f"Replace failed: {e}")
            self.status_message.emit(f"Replace failed: {e}")

    async def _do_import(self, asset: StandardAsset) -> None:
        """Execute import asynchronously."""
        try:
            if asset.status == AssetStatus.CLOUD:
                self.status_message.emit(f"Downloading {asset.name}...")
                asset = await self._do_download_for_import(asset)
                if asset.status != AssetStatus.LOCAL:
                    self.status_message.emit(
                        "Download failed, import cancelled")
                    return

            schema = self._plugin.get_settings_schema(asset)
            options: dict[str, Any] = {}

            if schema:
                options = self._show_settings_dialog(schema, asset)
                if options is None:
                    # User cancelled
                    logger.info("Import cancelled by user")
                    return

            options["renderer"] = self._view.get_selected_renderer()

            self.status_message.emit(f"Importing {asset.name}...")
            self._host.import_asset(asset, options)
            self.status_message.emit(f"Imported {asset.name}")

        except Exception as e:
            logger.error(f"Import failed: {e}")
            self.status_message.emit(f"Import failed: {e}")

    async def _do_download_for_import(self, asset: StandardAsset) -> StandardAsset:
        """Download an asset as part of import flow."""
        try:
            # TODO: Make resolution configurable and handle LOD's
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
            asset.status = AssetStatus.DOWNLOADING
            self._refresh_asset_in_view(asset)
            self._view.set_download_progress(asset.id, 0.0)

            self.status_message.emit(f"Downloading {asset.name}...")

            # TODO: Add progress callback support to plugin.download()
            resolution = "2k"  # TODO: Make resolution configurable and handle LOD's
            updated_asset = await self._plugin.download(asset, resolution)

            self._asset_cache[updated_asset.id] = updated_asset
            self._refresh_asset_in_view(updated_asset)
            self._view.set_download_progress(asset.id, 1.0)

            self.status_message.emit(f"Downloaded {asset.name}")
            logger.info(f"Download complete: {asset.name}")

            self.download_complete.emit()

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
            # TODO: write a dedicated refresh method for this, unclear intent
            self._view.set_items(list(self._asset_cache.values()))
            self.status_message.emit(f"Removed {asset.name}")

        except Exception as e:
            logger.error(f"Remove failed: {e}")
            self.status_message.emit(f"Remove failed: {e}")

    # ADD ASSETS FLOW

    # TODO: probably a better way to do this
    _SUPPORTED_EXTENSIONS = (
        "All Supported Files (*.hdr *.exr *.png *.jpg *.jpeg *.tif *.tiff "
        "*.obj *.fbx *.gltf *.glb *.usd *.usda *.usdc);;"
        "HDRIs (*.hdr *.exr);;"
        "Textures (*.png *.jpg *.jpeg *.tif *.tiff);;"
        "Models (*.obj *.fbx *.gltf *.glb *.usd *.usda *.usdc);;"
        "All Files (*)"
    )

    @Slot()
    def _on_add_files_requested(self) -> None:
        """Handle add files request from view."""
        from pathlib import Path

        files, _ = QFileDialog.getOpenFileNames(
            self._view,
            "Select Files to Import",
            "",
            self._SUPPORTED_EXTENSIONS,
        )

        if not files:
            return

        paths = [Path(f) for f in files]
        self._do_add_assets(paths)

    @Slot()
    def _on_add_folder_requested(self) -> None:
        """Handle add folder request from view."""
        from pathlib import Path

        directory = QFileDialog.getExistingDirectory(
            self._view,
            "Select Folder to Import",
            "",
        )

        if not directory:
            return

        self._do_add_assets(Path(directory))

    def _do_add_assets(self, paths: "Path | list[Path]") -> None:
        """
        Add assets from the given paths.

        Args:
            paths: Single path or list of paths (files or directories)
        """
        from pathlib import Path

        # Verify plugin supports local import
        if not isinstance(self._plugin, SupportsLocalImport):
            # note that this should never happen, but just in case
            logger.error("Plugin does not support local import")
            return

        if isinstance(paths, list):
            status_name = f"{len(paths)} items"
        else:
            status_name = paths.name

        self.status_message.emit(f"Adding {status_name}...")

        try:
            added_assets = self._plugin.add_assets(paths)

            if added_assets:
                for asset in added_assets:
                    self._asset_cache[asset.id] = asset

                self._view.set_items(list(self._asset_cache.values()))

                self.status_message.emit(f"Added {len(added_assets)} assets")
                logger.info(f"Added {len(added_assets)} assets")
            else:
                self.status_message.emit("No new assets found")

        except Exception as e:
            logger.error(f"Failed to add assets: {e}")
            self.status_message.emit(f"Failed to add assets: {e}")

    def _refresh_asset_in_view(self, asset: StandardAsset) -> None:
        """Refresh a single asset in the view."""
        # TODO: optimize, no need to refresh the entire list.
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

    def refresh(self) -> None:
        """
        Refresh the current view by re-running the current search.

        This is useful when external changes occur (e.g., an asset was
        downloaded in another tab and should now appear in the local library).
        """
        # TODO: difference between this and refreshing via cache is not clear
        logger.debug(f"Refreshing tab with query: '{self._current_query}'")
        self._run_async(self._do_search(self._current_query))

    def cleanup(self) -> None:
        """Clean up resources when tab is closed."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

        if self._thumbnail_worker is not None:
            self._thumbnail_worker.request_stop()
            self._thumbnail_worker.wait(1000)
            self._thumbnail_worker.deleteLater()
            self._thumbnail_worker = None

        self._asset_cache.clear()

        logger.debug(
            f"TabPresenter cleaned up for plugin: {self._plugin.plugin_id}")
