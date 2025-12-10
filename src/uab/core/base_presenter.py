from datetime import datetime
import pathlib as pl
from PySide6.QtCore import QObject, QTimer
import os
import subprocess
import platform
from typing import List, Dict, Tuple
import re
from collections import defaultdict

from uab.core import utils
from uab.core.assets import Asset
from uab.frontend.thumbnail import Thumbnail
from uab.backend.asset_service import AssetService


class Presenter(QObject):
    def __init__(self, view):
        super().__init__()
        LOCAL_ASSETS_DIR = "/Users/dev/Assets"
        SERVER_URL = "http://127.0.0.1:8000"
        self.asset_service = AssetService(SERVER_URL, LOCAL_ASSETS_DIR)
        self.ROOT_ASSET_DIRECTORY = "Assets"
        self.assets: list[Asset] = []
        self.thumbnails = []
        self.current_asset: Asset | None = None

        self.widget = view
        self.win = None

        # TODO: this is just placeholder
        self.widget.toolbar.set_allowed_renderers(
            ["Karma", "Mantra", "Renderman", "Redshift", "Arnold", "V-Ray"])

        self.bind_events()
        self._refresh_browser()

        self._refresh_gui_timer = QTimer(self)
        self._refresh_gui_timer.setInterval(30000)  # 30 seconds
        self._refresh_gui_timer.timeout.connect(
            self._automatically_refresh_browser)
        self._refresh_gui_timer.start()

    def bind_events(self):
        self.widget.search_text_changed.connect(self.on_search_changed)
        self.widget.filter_changed.connect(self.on_filter_changed)
        self.widget.import_clicked.connect(self.on_import_asset)
        self.widget.renderer_changed.connect(self.on_renderer_changed)
        self.widget.delete_asset_clicked.connect(self.on_delete_asset)
        self.widget.back_clicked.connect(self.on_back_clicked)
        self.widget.widget_closed.connect(self.on_widget_closed)
        self.widget.save_metadata_changes_clicked.connect(
            self.on_save_metadata_changes)

    def on_back_clicked(self) -> None:
        self.widget.show_browser()

    def on_widget_closed(self) -> None:
        self.asset_service.unregister_client(self.widget.client_id)

    def set_current_context_menu_options(self, thumbnail_context_menu_event: dict) -> List[dict]:
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "set_current_context_menu_options")

    def instantiate_asset(self, asset: Asset):
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "instantiate_asset")

    def _extract_base_name_and_resolution(self, file_path: pl.Path) -> Tuple[str, str | None]:
        """Extract base name and resolution from a file path.

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (base_name, resolution) where resolution is like "1k", "2k", "4k" or None
        """
        stem = file_path.stem
        # Pattern to match resolution suffixes like "1k", "2k", "4k", "8k", etc.
        resolution_pattern = r'[._-](\d+k)$'
        match = re.search(resolution_pattern, stem, re.IGNORECASE)

        if match:
            resolution = match.group(1).lower()
            # Remove the resolution suffix to get base name
            base_name = re.sub(resolution_pattern, '',
                               stem, flags=re.IGNORECASE)
            return base_name, resolution
        else:
            # No resolution found, return the stem as base name
            return stem, None

    def _group_files_by_lod(self, file_paths: List[pl.Path]) -> Dict[str, Dict[str, pl.Path]]:
        """Group files by base name and resolution.

        Args:
            file_paths: List of file paths to group

        Returns:
            Dictionary mapping base_name to a dict of {resolution: file_path}
        """
        grouped = defaultdict(dict)

        for file_path in file_paths:
            base_name, resolution = self._extract_base_name_and_resolution(
                file_path)
            if resolution:
                grouped[base_name][resolution] = file_path
            else:
                # Files without resolution suffix are treated as base assets
                # Use empty string as key to indicate it's the base/primary file
                grouped[base_name][""] = file_path

        return dict(grouped)

    def on_import_asset(self, asset_path):
        if not asset_path:
            print("Importing asset: MISSING PATH")
            return

        if os.path.isdir(asset_path):
            print(
                f"Importing assets from directory (including nested): {asset_path}")
            imported_count = 0
            skipped_count = 0
            root_path = pl.Path(asset_path)

            # Collect all .hdr/.exr files first
            hdri_files = []
            for file_path in root_path.rglob('*'):
                if file_path.is_file():
                    filename = file_path.name.lower()
                    if filename.endswith('.hdr') or filename.endswith('.exr'):
                        hdri_files.append(file_path)
                    else:
                        skipped_count += 1

            # Group files by base name to detect LODs
            grouped_files = self._group_files_by_lod(hdri_files)

            # Process each group
            for base_name, resolution_files in grouped_files.items():
                # If we have multiple resolutions (LODs), create one asset with LODs
                if len(resolution_files) > 1 and any(res != "" for res in resolution_files.keys()):
                    # Find the base file (without resolution) or use the first one
                    base_file = resolution_files.get(
                        "") or list(resolution_files.values())[0]

                    # Build LOD dictionary (excluding the base file if it's marked with "")
                    lods = {}
                    for res, file_path in resolution_files.items():
                        if res:  # Only add non-empty resolution keys
                            lods[res] = str(file_path)

                    # Use the base file for the main asset path
                    asset = self.asset_service.create_asset_request_body(
                        str(base_file),
                        name=utils.file_name_to_display_name(base_file),
                        tags=utils.tags_from_file_name(base_file),
                        lods=lods if lods else None,
                        current_lod=list(lods.keys())[0] if lods else None,
                    )
                    self.asset_service.add_asset_to_db(asset)
                    imported_count += 1
                else:
                    # Single file or no resolution pattern, import as regular asset
                    file_path = list(resolution_files.values())[0]
                    asset = self.asset_service.create_asset_request_body(
                        str(file_path),
                        name=utils.file_name_to_display_name(file_path),
                        tags=utils.tags_from_file_name(file_path))
                    self.asset_service.add_asset_to_db(asset)
                    imported_count += 1

            self._refresh_browser()
            self.widget.show_message(
                f"Imported {imported_count} .hdr/.exr asset(s) from directory (including nested). Skipped {skipped_count} non-hdr/exr file(s).", "info", 3000)
        else:
            print(f"Importing asset: {asset_path}")
            asset = self.asset_service.create_asset_request_body(
                asset_path,
                name=utils.file_name_to_display_name(pl.Path(asset_path)),
                tags=utils.tags_from_file_name(pl.Path(asset_path)))
            self.asset_service.add_asset_to_db(asset)
            self._refresh_browser()
            self.widget.show_message(
                f"Imported asset! {asset.name}", "info", 3000)

    def on_delete_asset(self, asset: Asset):
        if asset.id is None:
            print("Error: Cannot remove asset without id")
            return
        self.asset_service.remove_asset_from_db(asset.id)
        self._refresh_browser()
        self.widget.show_browser()
        self.widget.show_message(
            f"Removed asset: {asset.name}", "info", 3000)

    def on_renderer_changed(self, renderer_text: str):
        self.widget.show_message(
            f"Renderer changed to {renderer_text}", "info", 3000)

    def on_asset_thumbnail_clicked(self, asset: Asset) -> None:
        if asset.id is None:
            print("Error: Asset has no id")
            return
        thumbnail = self.get_thumbnail_by_id(asset.id)
        self.current_asset = asset
        self.widget.set_new_selected_thumbnail(thumbnail)
        self.widget.show_message(
            f"Asset clicked: {self.current_asset.name}", "info", 3000)

    def get_thumbnail_by_id(self, id: int) -> Thumbnail:
        return next((p for p in self.thumbnails if p.asset_id == id), None)

    def on_asset_thumbnail_double_clicked(self, asset: Asset):
        self.widget.show_asset_detail(asset)

    def on_edit_metadata(self, asset: Asset):
        pass

    def on_save_metadata_changes(self, asset: Asset):
        self.asset_service.update_asset(asset)
        self._refresh_browser()
        self.widget.show_message(
            f"Saved metadata changes for asset: {asset.name}", "info", 3000)

    def _automatically_refresh_browser(self):
        # TODO: make this smarter: only refresh if there's anything new.
        # Maybe only pull in new/changed assets, not all of them?
        if not self.widget.is_browser_visible():
            return
        self._refresh_browser()

    def _refresh_browser(self):
        self.assets = self._load_assets()
        self.thumbnails = self._create_thumbnails_list(self.assets)
        self.widget.draw_thumbnails(self.thumbnails)
        self.widget.show_message(
            f"Browser refreshed!", "info", 2000)

    def _load_assets(self):
        return self.asset_service.get_assets()

    def _create_thumbnails_list(self, assets: list[Asset]) -> List[Thumbnail]:
        """
        From a flat list of Asset objects, create a list of Thumbnail widgets.
        """
        thumbnails: List[Thumbnail] = []
        if not assets:
            return thumbnails

        for asset in assets:
            asset_thumbnail = Thumbnail(
                asset,
                parent=None,
            )
            # Connect events
            asset_thumbnail.asset_double_clicked.connect(
                self.on_asset_thumbnail_double_clicked)
            asset_thumbnail.asset_clicked.connect(
                self.on_asset_thumbnail_clicked)
            asset_thumbnail.open_image_requested.connect(
                self.on_open_image_requested)
            asset_thumbnail.reveal_in_file_system_requested.connect(
                self.on_reveal_in_file_system_requested)
            asset_thumbnail.instantiate_requested.connect(
                self.on_instantiate_requested)
            asset_thumbnail.context_menu_requested.connect(
                self.set_current_context_menu_options)
            asset_thumbnail.replace_texture_requested.connect(
                self.on_replace_texture_requested)
            thumbnails.append(asset_thumbnail)

        return thumbnails

    def on_open_image_requested(self, asset: Asset) -> None:
        print(f"Opening image for asset: {asset.name}")
        self.widget.show_message(
            f"Opening image for asset: {asset.name}", "info", 3000)
        if platform.system() == 'Darwin':
            subprocess.call(('open', asset.path))
        elif platform.system() == 'Windows':
            os.startfile(asset.path)

    def on_reveal_in_file_system_requested(self, asset: Asset) -> None:
        print(f"Revealing in file system for asset: {asset.name}")
        asset_path = pl.Path(asset.path)
        if platform.system() == "Windows":
            os.startfile(str(asset_path.parent))
        elif platform.system() == "Darwin":
            subprocess.call(('open', str(asset_path.parent)))

    def on_instantiate_requested(self, asset: Asset) -> None:
        print(f"Instantiating asset: {asset.name}")
        self.instantiate_asset(asset)

    def on_replace_texture_requested(self, asset: Asset) -> None:
        print(f"Replacing texture for asset: {asset.name}")
        self.replace_texture(asset)

    def replace_texture(self, asset: Asset) -> None:
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "replace_texture")

    def on_search_changed(self, text: str, delay: int = 200) -> None:
        if not hasattr(self, "_search_debounce_timer"):
            self._search_debounce_timer = QTimer(self)
            self._search_debounce_timer.setSingleShot(True)
            self._search_debounce_timer.timeout.connect(self._trigger_search)

        self._pending_search_text = text
        self._search_debounce_timer.start(delay)

    def _trigger_search(self):
        text = getattr(self, "_pending_search_text", "")
        filtered_assets = self.asset_service.search_assets(text)
        self.widget.draw_thumbnails(
            self._create_thumbnails_list(filtered_assets))
        self.widget.show_browser()

    def on_filter_changed(self, text: str):
        print(f"Filter changed: {text}")


class ImplementedByDerivedClassError(Exception):
    """
    Exception raised when a method that must be implemented by the derived class is called.
    """

    def __init__(self, class_name: str, method_name: str):
        self.message = f"<{method_name}> must be implemented by a derived class of <{class_name}>."
        super().__init__(self.message)

    def __str__(self):
        return self.message
