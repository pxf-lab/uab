"""Tab presenter for Universal Asset Browser.

Each tab in the browser has its own TabPresenter that coordinates
between the plugin (data source) and the BrowserView (UI).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication, QWidget
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

from uab.core.interfaces import Browsable, SupportsLocalImport
from uab.core.models import Asset, AssetStatus, AssetType, CompositeAsset, StandardAsset
from uab.core.thumbnails import propagate_preferred_thumbnail
from uab.ui.utils import ThumbnailLoaderBase

if TYPE_CHECKING:
    from pathlib import Path
    from uab.core.interfaces import AssetLibraryPlugin, HostIntegration
    from uab.ui.browser import BrowserView

logger = logging.getLogger(__name__)

_QT_ASYNCIO_LOOP: asyncio.AbstractEventLoop | None = None
_QT_ASYNCIO_TIMER: QTimer | None = None


def _ensure_qt_asyncio_loop() -> asyncio.AbstractEventLoop | None:
    """
    Ensure an asyncio event loop is being pumped by Qt.

    This avoids blocking the UI thread with `asyncio.run(...)` in embedded hosts
    like Maya/Houdini/standalone Qt apps.

    Returns:
        The managed event loop, or None if Qt isn't running.
    """
    # TODO: come back to this, I am reallys ure that there's a better solution
    global _QT_ASYNCIO_LOOP, _QT_ASYNCIO_TIMER

    # don't treat mocks as a real running Qt environment
    if not (isinstance(QApplication, type) and isinstance(QTimer, type)):
        return None

    app = QApplication.instance()
    if app is None:
        return None

    if _QT_ASYNCIO_LOOP is not None and not _QT_ASYNCIO_LOOP.is_closed():
        return _QT_ASYNCIO_LOOP

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    timer = QTimer()
    timer.setInterval(10)  # ms; small slices to keep UI responsive

    def _step() -> None:
        if loop.is_closed():
            timer.stop()
            return
        try:
            # Prevent the loop from blocking the UI thread.
            loop.call_soon(loop.stop)
            loop.run_forever()
        except Exception as e:
            logger.debug(f"Asyncio Qt pump failed: {e}")
            timer.stop()

    timer.timeout.connect(_step)
    timer.start()

    def _shutdown() -> None:
        try:
            timer.stop()
        except Exception:
            pass
        try:
            loop.stop()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass

    try:
        app.aboutToQuit.connect(_shutdown)  # type: ignore[attr-defined]
    except Exception:
        pass

    _QT_ASYNCIO_LOOP = loop
    _QT_ASYNCIO_TIMER = timer
    return loop


def get_thumbnail_cache_path(item: Any, plugin_id: str) -> "Path":
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

    ext = ".jpg"  # Default thumbnail extension, below checks for a different extension from the query
    thumbnail_url = getattr(item, "thumbnail_url", None)
    if thumbnail_url:
        url_path = thumbnail_url.split("?")[0]
        url_ext = PathLib(url_path).suffix.lower()
        if url_ext:
            ext = url_ext

    external_id = getattr(item, "external_id",
                          None) or getattr(item, "id", "item")
    cache_filename = f"{external_id}{ext}"
    return cache_dir / cache_filename


class NetworkThumbnailLoader(ThumbnailLoaderBase):
    """
    Background worker thread for fetching thumbnails from network.

    Emits signals when thumbnails are ready so the main thread can
    update the UI safely.

    Uses synchronous HTTP requests (urllib) instead of aiohttp because
    aiohttp sessions are not thread-safe and can't be shared across threads.
    """

    thumbnail_ready = Signal(str, object)  # asset_id, Path or None

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._plugin_id = plugin.plugin_id

    def set_items_to_fetch(self, items: list[Browsable]) -> None:
        """Set the items to fetch thumbnails for."""
        self.set_items(items)

    def _process_item(self, item: Browsable) -> None:
        """
        Process a single asset by fetching its thumbnail.

        Args:
            item: The StandardAsset to fetch thumbnail for
        """
        thumb_path = self._fetch_thumbnail_sync(item)
        self.thumbnail_ready.emit(item.id, thumb_path)

    def _fetch_thumbnail_sync(self, item: Browsable) -> "Path | None":
        """
        Fetch a single thumbnail using synchronous HTTP (urllib).

        This avoids aiohttp thread-safety issues by using stdlib urllib.
        """
        import urllib.request  # use instead of requests to minimize dependencies
        import urllib.error

        thumbnail_url = item.thumbnail_url
        if not thumbnail_url:
            return None

        cache_path = get_thumbnail_cache_path(item, self._plugin_id)

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

            logger.debug(f"Downloaded thumbnail for {item.name}")
            return cache_path

        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            logger.debug(f"Failed to fetch thumbnail for {item.name}: {e}")
            return None
        except Exception as e:
            logger.debug(
                f"Unexpected error fetching thumbnail for {item.name}: {e}")
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
    # payload: dict with downloaded IDs, etc.
    download_complete = Signal(object)

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

        # current top-level items shown in the grid (assets and/or composites)
        self._current_items: list[Browsable] = []

        # cache of all known items by ID (includes expanded composite children)
        self._item_cache: dict[str, Browsable] = {}

        # child → parent composite ID mapping (built when composites are expanded)
        self._parent_map: dict[str, str] = {}

        # composite IDs that have been expanded (avoid re-fetching)
        self._expanded_composites: set[str] = set()

        self._is_loading = False

        self._current_query: str = ""

        self._thumbnail_worker: NetworkThumbnailLoader | None = None

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
        # back-compat: existing BrowserView emits a single download_requested(item_id)
        self._view.download_requested.connect(self._on_download_requested)

        # Forward-compat: tree/detail UI will emit separate download signals
        download_asset_sig = getattr(
            self._view, "download_asset_requested", None)
        if download_asset_sig is not None:
            download_asset_sig.connect(self._on_download_asset_requested)

        download_comp_sig = getattr(
            self._view, "download_composite_requested", None)
        if download_comp_sig is not None:
            download_comp_sig.connect(self._on_download_composite_requested)

        self._view.remove_requested.connect(self._on_remove_requested)
        self._view.new_asset_requested.connect(self._on_new_asset_requested)
        self._view.replace_asset_requested.connect(
            self._on_replace_asset_requested)

    def _trigger_initial_search(self) -> None:
        """Trigger an initial empty search to populate the view."""
        QTimer.singleShot(0, lambda: self._on_search_requested(""))

    # ASYNC HELPERS

    async def _close_plugin_resources(self) -> None:
        """
        Best-effort cleanup for plugin-held async resources (here specifically for aiohttp sessions

        If an aiohttp session/connector is left open when a loop is torn down, Python will warn about pending aiohttp cleanup tasks.
        """
        close_fn = getattr(self._plugin, "close", None)
        if close_fn is None or not callable(close_fn):
            return

        try:
            maybe = close_fn()
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception as e:
            logger.debug(f"Plugin resource cleanup failed: {e}")

    async def _run_with_cleanup(self, coro) -> None:
        try:
            await coro
        finally:
            await self._close_plugin_resources()

    def _run_async(self, coro) -> asyncio.Task | None:
        """
        Run an async coroutine, handling event loop setup.

        # TODO: Use qasync for event loop management
        """
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            # TODO: is this really the best way to do this
            if isinstance(QWidget, type) and isinstance(self._view, QWidget):
                qt_loop = _ensure_qt_asyncio_loop()
                if qt_loop is not None:
                    try:
                        return qt_loop.create_task(coro)
                    except Exception as e:
                        logger.error(
                            f"Failed to schedule async task on Qt loop: {e}")

            try:
                asyncio.run(self._run_with_cleanup(coro))
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
            items = await self._plugin.search(query)

            self._current_items = list(items)
            self._item_cache.clear()
            self._parent_map.clear()
            self._expanded_composites.clear()

            for item in items:
                self._item_cache[item.id] = item

            self._view.set_items(items)

            logger.info(f"Search complete: {len(items)} items found")
            self.status_message.emit(f"Found {len(items)} items")

            self._queue_thumbnail_fetch(items)

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

    def _queue_thumbnail_fetch(self, items: list[Browsable]) -> None:
        """
        Queue thumbnails for background fetching using a worker thread.

        First checks for already-cached thumbnails on disk and uses those directly.
        Only queues assets that actually need to be downloaded.
        """
        plugin_id = self._plugin.plugin_id
        items_needing_download: list[Browsable] = []
        cached_count = 0

        for item in items:
            if not item.thumbnail_url:
                continue

            if item.thumbnail_path and item.thumbnail_path.exists():
                continue

            cache_path = get_thumbnail_cache_path(item, plugin_id)
            if cache_path.exists():
                item.thumbnail_path = cache_path
                self._item_cache[item.id] = item
                cached_count += 1
            else:
                items_needing_download.append(item)

        if cached_count > 0:
            logger.debug(f"Found {cached_count} cached thumbnails on disk")
            self._view.set_items(self._current_items)

        if not items_needing_download:
            logger.debug("All thumbnails already cached")
            return

        if not hasattr(self._plugin, "download_thumbnail"):
            logger.debug("Plugin does not support thumbnail downloading")
            return

        logger.debug(
            f"Queueing {len(items_needing_download)} thumbnails for download")

        if self._thumbnail_worker is not None:
            self._thumbnail_worker.request_stop()
            self._thumbnail_worker.wait(1000)  # Wait up to 1 second
            self._thumbnail_worker.deleteLater()

        self._thumbnail_worker = NetworkThumbnailLoader(self._plugin, self)
        self._thumbnail_worker.thumbnail_ready.connect(
            self._on_thumbnail_ready)
        self._thumbnail_worker.batch_complete.connect(
            self._on_thumbnail_batch_complete)
        self._thumbnail_worker.all_complete.connect(
            self._on_thumbnails_complete)
        self._thumbnail_worker.set_items_to_fetch(items_needing_download)
        self._thumbnail_worker.start()

    @Slot(str, object)
    def _on_thumbnail_ready(self, item_id: str, thumb_path) -> None:
        """Handle a thumbnail being ready (called on main thread via signal)."""
        if thumb_path and item_id in self._item_cache:
            item = self._item_cache[item_id]
            item.thumbnail_path = thumb_path
            if isinstance(item, CompositeAsset):
                # If this composite contains LOCAL HDRI/Model leaf assets, ensure they
                # use the downloaded thumbnail instead of dynamically rendering previews.
                propagate_preferred_thumbnail(item)
            self._item_cache[item_id] = item

    @Slot()
    def _on_thumbnail_batch_complete(self) -> None:
        """Handle a batch of thumbnails being complete - update the view."""
        self._view.set_items(self._current_items)

    @Slot()
    def _on_thumbnails_complete(self) -> None:
        """Handle all thumbnails being complete - final view update."""
        self._view.set_items(self._current_items)
        logger.debug("All thumbnails fetched")

    # Keep async versions for compatibility with code that uses qasync
    async def _fetch_thumbnails(self, items: list[Browsable]) -> None:
        """Fetch thumbnails for items that have URLs but no local path."""
        items_needing_thumbs = [
            i
            for i in items
            if i.thumbnail_url and (not i.thumbnail_path or not i.thumbnail_path.exists())
        ]

        if not items_needing_thumbs:
            return

        logger.debug(f"Fetching {len(items_needing_thumbs)} thumbnails")

        if not hasattr(self._plugin, "download_thumbnail"):
            logger.debug("Plugin does not support thumbnail downloading")
            return

        batch_size = 10
        for i in range(0, len(items_needing_thumbs), batch_size):
            batch = items_needing_thumbs[i:i + batch_size]
            tasks = []
            for item in batch:
                tasks.append(self._fetch_single_thumbnail(item))

            await asyncio.gather(*tasks, return_exceptions=True)
            self._view.set_items(self._current_items)

    async def _fetch_single_thumbnail(self, item: Browsable) -> None:
        """Fetch thumbnail for a single item."""
        try:
            # type: ignore[attr-defined]
            thumb_path = await self._plugin.download_thumbnail(item)
            if thumb_path:
                item.thumbnail_path = thumb_path
                self._item_cache[item.id] = item
                logger.debug(f"Thumbnail fetched for {item.name}")
        except Exception as e:
            logger.debug(f"Failed to fetch thumbnail for {item.name}: {e}")

    def _index_composite_tree(self, composite: CompositeAsset) -> None:
        """Index a composite and all descendants into caches."""
        self._item_cache[composite.id] = composite
        for child in composite.children:
            if isinstance(child, CompositeAsset):
                self._parent_map[child.id] = composite.id
                self._index_composite_tree(child)
            elif isinstance(child, (Asset, StandardAsset)):
                self._parent_map[child.id] = composite.id
                self._item_cache[child.id] = child

    def _replace_current_item(self, item: Browsable) -> None:
        """Replace a top-level item in-place (by ID) if present."""
        for idx, existing in enumerate(self._current_items):
            if existing.id == item.id:
                self._current_items[idx] = item
                break

    def _as_standard_asset(self, item: Browsable) -> StandardAsset:
        """Convert an Asset to StandardAsset for host APIs."""
        # TODO: come back to this
        if isinstance(item, StandardAsset):
            return item
        if isinstance(item, Asset):
            return StandardAsset(
                id=item.id,
                source=item.source,
                external_id=item.external_id,
                name=item.name,
                type=item.asset_type,
                status=item.status,
                local_path=item.local_path,
                thumbnail_url=item.thumbnail_url or "",
                thumbnail_path=item.thumbnail_path,
                metadata=item.metadata.copy()
                if isinstance(item.metadata, dict)
                else {},
            )
        raise TypeError(f"Cannot convert to StandardAsset: {type(item)}")

    @Slot(str)
    def _on_detail_requested(self, item_id: str) -> None:
        """Handle detail view request."""
        self._run_async(self._do_show_detail(item_id))

    async def _do_show_detail(self, item_id: str) -> None:
        """Show detail view for an item, expanding composites lazily."""
        item = self._item_cache.get(item_id)
        if not item:
            logger.warning(f"Item not found in cache: {item_id}")
            return

        if isinstance(item, CompositeAsset) and not item.children and item.id not in self._expanded_composites:
            try:
                expanded = await self._plugin.expand_composite(item)
                self._expanded_composites.add(item.id)
                self._replace_current_item(expanded)
                self._index_composite_tree(expanded)
                item = expanded
            except NotImplementedError:
                logger.debug("Plugin does not implement expand_composite()")
            except Exception as e:
                logger.error(f"Failed to expand composite {item.name}: {e}")
                self.status_message.emit(f"Failed to expand {item.name}: {e}")

        if isinstance(item, CompositeAsset):
            propagate_preferred_thumbnail(item)

        # UI will be updated to support composites
        self._view.show_detail(item)

    @Slot(str)
    def _on_import_requested(self, item_id: str) -> None:
        """Handle import request."""
        item = self._item_cache.get(item_id)
        if not item:
            logger.warning(f"Item not found for import: {item_id}")
            return

        self._run_async(self._do_import(item))

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
        item = self._item_cache.get(asset_id)
        if not item:
            logger.warning(f"Item not found for replace: {asset_id}")
            return
        if isinstance(item, CompositeAsset):
            logger.warning(
                f"Cannot replace selection with composite: {item.name}")
            return

        try:
            asset = self._as_standard_asset(item)
            self.status_message.emit(f"Replacing with {asset.name}...")
            self._host.update_selection(asset)
            self.status_message.emit(f"Replaced with {asset.name}")
        except Exception as e:
            logger.error(f"Replace failed: {e}")
            self.status_message.emit(f"Replace failed: {e}")

    async def _do_import(self, item: Browsable) -> None:
        """Execute import asynchronously (asset or composite)."""
        try:
            if isinstance(item, CompositeAsset):
                # Ensure composite is expanded before import
                if not item.children and item.id not in self._expanded_composites:
                    item = await self._plugin.expand_composite(item)
                    self._expanded_composites.add(item.id)
                    self._replace_current_item(item)
                    self._index_composite_tree(item)

                schema = self._plugin.get_settings_schema(item)
                options: dict[str, Any] = {}
                if schema:
                    options = self._show_settings_dialog(schema, item)
                    if options is None:
                        logger.info("Import cancelled by user")
                        return
                options["renderer"] = self._view.get_selected_renderer()

                self.status_message.emit(f"Importing {item.name}...")
                # type: ignore[attr-defined]
                self._host.import_composite(item, options)
                self.status_message.emit(f"Imported {item.name}")
                return

            # Asset import (single leaf)
            asset_item: Browsable = item
            status = getattr(asset_item, "status", asset_item.display_status)
            if status == AssetStatus.CLOUD:
                self.status_message.emit(f"Downloading {asset_item.name}...")
                asset_item = await self._do_download_for_import(asset_item)
                status = getattr(asset_item, "status",
                                 asset_item.display_status)
                if status != AssetStatus.LOCAL:
                    self.status_message.emit(
                        "Download failed, import cancelled")
                    return

            schema = self._plugin.get_settings_schema(
                asset_item)  # type: ignore[arg-type]
            options: dict[str, Any] = {}

            if schema:
                options = self._show_settings_dialog(schema, asset_item)
                if options is None:
                    # User cancelled
                    logger.info("Import cancelled by user")
                    return

            options["renderer"] = self._view.get_selected_renderer()

            std_asset = self._as_standard_asset(asset_item)
            self.status_message.emit(f"Importing {std_asset.name}...")
            self._host.import_asset(std_asset, options)
            self.status_message.emit(f"Imported {std_asset.name}")

        except Exception as e:
            logger.error(f"Import failed: {e}")
            self.status_message.emit(f"Import failed: {e}")

    async def _do_download_for_import(self, item: Browsable) -> Browsable:
        """Download an asset as part of import flow."""
        try:
            # For legacy StandardAsset plugins, fall back to `download()`.
            if isinstance(item, StandardAsset) and hasattr(self._plugin, "download"):
                resolution = "2k"
                # type: ignore[attr-defined]
                updated = await self._plugin.download(item, resolution)
                self._item_cache[updated.id] = updated
                return updated

            if isinstance(item, Asset):
                updated = await self._plugin.download_asset(item)
                self._item_cache[updated.id] = updated
                return updated

            return item
        except Exception as e:
            logger.error(f"Download for import failed: {e}")
            return item

    def _show_settings_dialog(
        self, schema: dict[str, Any], item: Browsable
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
        dialog.setWindowTitle(f"Import Settings - {item.name}")
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
    def _on_download_requested(self, item_id: str) -> None:
        """Handle download request (back-compat signal)."""
        item = self._item_cache.get(item_id)
        if not item:
            logger.warning(f"Item not found for download: {item_id}")
            return

        if isinstance(item, CompositeAsset):
            self._on_download_composite_requested(item_id, None)
            return

        self._on_download_asset_requested(item_id)

    @Slot(str)
    def _on_download_asset_requested(self, asset_id: str) -> None:
        """Handle request to download a single Asset."""
        self._run_async(self._do_download_asset(asset_id))

    @Slot(str, object)
    def _on_download_composite_requested(self, composite_id: str, resolution) -> None:
        """Handle request to download a composite (optionally filtered by resolution)."""
        resolution_str = resolution if isinstance(resolution, str) else None
        self._run_async(self._do_download_composite(
            composite_id, resolution_str))

    def _replace_child_in_parent(self, child_id: str, new_child: Browsable) -> None:
        """Replace a cached child item inside its parent composite (if known)."""
        parent_id = self._parent_map.get(child_id)
        if not parent_id:
            return
        parent = self._item_cache.get(parent_id)
        if not isinstance(parent, CompositeAsset):
            return

        for idx, existing in enumerate(parent.children):
            if getattr(existing, "id", None) == new_child.id:
                parent.children[idx] = new_child  # type: ignore[list-item]
                break

    def _refresh_items_in_view(self) -> None:
        """Refresh view with current top-level items."""
        self._view.set_items(self._current_items)

    async def _do_download_asset(self, asset_id: str) -> None:
        """Execute a single-asset download asynchronously."""
        item = self._item_cache.get(asset_id)
        if not item:
            logger.warning(f"Item not found for download: {asset_id}")
            return
        if isinstance(item, CompositeAsset):
            logger.warning(
                f"Cannot download composite via asset handler: {item.name}")
            return

        status = getattr(item, "status", item.display_status)
        if status != AssetStatus.CLOUD:
            logger.info(f"Item {asset_id} is not a cloud asset")
            return

        original_status = status
        try:
            # Update UI to DOWNLOADING (only applies to leaf assets)
            if hasattr(item, "status"):
                # type: ignore[attr-defined]
                item.status = AssetStatus.DOWNLOADING
            self._item_cache[item.id] = item
            self._replace_child_in_parent(item.id, item)
            self._refresh_items_in_view()
            self._view.set_download_progress(item.id, 0.0)

            self.status_message.emit(f"Downloading {item.name}...")

            updated: Browsable
            if isinstance(item, Asset):
                updated = await self._plugin.download_asset(item)
            elif isinstance(item, StandardAsset) and hasattr(self._plugin, "download"):
                resolution = "2k"
                # type: ignore[attr-defined]
                updated = await self._plugin.download(item, resolution)
            else:
                raise NotImplementedError(
                    f"Plugin does not support downloading this item type: {type(item)}"
                )

            self._item_cache[updated.id] = updated
            self._replace_current_item(updated)
            self._replace_child_in_parent(updated.id, updated)
            self._refresh_items_in_view()
            self._view.set_download_progress(updated.id, 1.0)

            self.status_message.emit(f"Downloaded {updated.name}")
            logger.info(f"Download complete: {updated.name}")

            self.download_complete.emit(
                {"source": self._plugin.plugin_id,
                    "downloaded_item_ids": [updated.id]}
            )

        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.status_message.emit(f"Download failed: {e}")

            # Restore status if possible
            if hasattr(item, "status"):
                item.status = original_status  # type: ignore[attr-defined]
            self._item_cache[item.id] = item
            self._replace_child_in_parent(item.id, item)
            self._refresh_items_in_view()
            self._view.set_download_progress(item.id, -1)

    async def _do_download_composite(self, composite_id: str, resolution: str | None) -> None:
        """Execute a composite download asynchronously."""
        item = self._item_cache.get(composite_id)
        if not isinstance(item, CompositeAsset):
            logger.warning(f"Composite not found for download: {composite_id}")
            return

        try:
            self.status_message.emit(f"Downloading {item.name}...")
            updated = await self._plugin.download_composite(item, resolution=resolution, recursive=True)

            # Replace + re-index expanded tree
            self._expanded_composites.add(updated.id)
            self._replace_current_item(updated)
            self._index_composite_tree(updated)

            self._refresh_items_in_view()

            downloaded_asset_ids = [
                a.id
                for a in updated.get_all_assets()
                if isinstance(a, Asset) and a.status == AssetStatus.LOCAL
            ]
            self.status_message.emit(f"Downloaded {updated.name}")

            self.download_complete.emit(
                {"source": self._plugin.plugin_id,
                    "downloaded_item_ids": downloaded_asset_ids}
            )

        except Exception as e:
            logger.error(f"Composite download failed: {e}")
            self.status_message.emit(f"Composite download failed: {e}")

    @Slot(str)
    def _on_remove_requested(self, item_id: str) -> None:
        """Handle remove request."""
        item = self._item_cache.get(item_id)
        if not item:
            logger.warning(f"Item not found for removal: {item_id}")
            return
        if isinstance(item, CompositeAsset):
            logger.info("Removal is not supported for composites")
            return

        if not self._plugin.can_remove:
            logger.info("Plugin does not support removal")
            return

        reply = QMessageBox.question(
            self._view,
            "Remove Asset",
            f"Remove '{item.name}' from the library?\n\n"
            "This will delete the local files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._run_async(self._do_remove(item_id))

    async def _do_remove(self, item_id: str) -> None:
        """Execute removal asynchronously."""
        try:
            item = self._item_cache.get(item_id)
            if not item:
                return

            # TODO: Call plugin.remove() when available
            self._item_cache.pop(item_id, None)
            self._current_items = [
                i for i in self._current_items if i.id != item_id]

            self._refresh_items_in_view()
            self.status_message.emit(f"Removed {item.name}")

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
                    self._item_cache[asset.id] = asset
                    self._current_items.append(asset)

                self._refresh_items_in_view()

                self.status_message.emit(f"Added {len(added_assets)} assets")
                logger.info(f"Added {len(added_assets)} assets")
            else:
                self.status_message.emit("No new assets found")

        except Exception as e:
            logger.error(f"Failed to add assets: {e}")
            self.status_message.emit(f"Failed to add assets: {e}")

    def _refresh_asset_in_view(self, asset: Browsable) -> None:
        """Refresh items in the view (legacy helper)."""
        self._refresh_items_in_view()

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

        self._current_items.clear()
        self._item_cache.clear()
        self._parent_map.clear()
        self._expanded_composites.clear()

        logger.debug(
            f"TabPresenter cleaned up for plugin: {self._plugin.plugin_id}")
