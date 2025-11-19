import pathlib as pl
from PySide6.QtCore import QObject, QTimer
import os
import subprocess
import platform
from typing import List

from uab.frontend.thumbnail import Thumbnail
from uab.backend.asset_service import AssetService


class Presenter(QObject):
    def __init__(self, view):
        super().__init__()
        LOCAL_ASSETS_DIR = "/Users/dev/Assets"
        SERVER_URL = "http://127.0.0.1:8000"
        self.asset_service = AssetService(SERVER_URL, LOCAL_ASSETS_DIR)
        self.ROOT_ASSET_DIRECTORY = "Assets"
        self.assets = []
        self.thumbnails = []
        self.current_asset = None

        self.widget = view
        self.win = None

        # TODO: this is just placeholder
        self.widget.toolbar.set_allowed_renderers(
            ["Karma", "Mantra", "Renderman", "Redshift", "Arnold", "V-Ray"])

        self.bind_events()
        self._refresh_browser()

        self._refresh_gui_timer = QTimer(self)
        self._refresh_gui_timer.setInterval(5000)  # 5 seconds
        self._refresh_gui_timer.timeout.connect(self._refresh_browser)
        self._refresh_gui_timer.start()

    def bind_events(self):
        self.widget.search_text_changed.connect(self.on_search_changed)
        self.widget.filter_changed.connect(self.on_filter_changed)
        self.widget.import_clicked.connect(self.on_import_asset)
        self.widget.renderer_changed.connect(self.on_renderer_changed)
        self.widget.delete_asset_clicked.connect(self.on_delete_asset)
        self.widget.back_clicked.connect(self.on_back_clicked)
        self.widget.widget_closed.connect(self.on_widget_closed)

    def on_back_clicked(self) -> None:
        self.widget.show_browser()

    def on_widget_closed(self) -> None:
        self.asset_service.unregister_client(self.widget.client_id)

    def set_current_context_menu_options(self, thumbnail_context_menu_event: dict) -> List[dict]:
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "set_current_context_menu_options")

    def instantiate_asset(self, asset: dict):
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "instantiate_asset")

    def on_import_asset(self, asset_path):
        if not asset_path:
            print("Importing asset: MISSING PATH")
            return

        if os.path.isdir(asset_path):
            print(f"Importing assets from directory: {asset_path}")
            imported_count = 0
            skipped_count = 0
            print(os.listdir(asset_path))
            for filename in os.listdir(asset_path):
                file_path = os.path.join(asset_path, filename)
                # TODO: add support for other file types
                if os.path.isfile(file_path) and filename.lower().endswith('.hdr'):
                    asset = self.asset_service.create_asset_request_body(
                        file_path)
                    self.asset_service.add_asset_to_db(asset)
                    imported_count += 1
                else:
                    skipped_count += 1
            self._refresh_browser()
            self.widget.show_message(
                f"Imported {imported_count} .hdr asset(s) from directory. Skipped {skipped_count} non-hdr file(s).", "info", 3000)
        else:
            print(f"Importing asset: {asset_path}")
            asset = self.asset_service.create_asset_request_body(
                asset_path)
            self.asset_service.add_asset_to_db(asset)
            self._refresh_browser()
            self.widget.show_message(
                f"Imported asset! {asset['name']}", "info", 3000)

    def on_delete_asset(self, asset_id):
        self.asset_service.remove_asset_from_db(asset_id)
        self._refresh_browser()
        self.widget.show_browser()
        self.widget.show_message(f"Deleted asset!", "info", 3000)

    def on_renderer_changed(self, renderer_text: str):
        self.widget.show_message(
            f"Renderer changed to {renderer_text}", "info", 3000)

    def on_asset_thumbnail_clicked(self, asset: dict) -> None:
        thumbnail = self.get_thumbnail_by_id(asset['id'])
        self.current_asset = asset
        self.widget.set_new_selected_thumbnail(thumbnail)
        self.widget.show_message(
            f"Asset clicked: {self.current_asset['name']}", "info", 3000)

    def get_thumbnail_by_id(self, id: int) -> Thumbnail:
        return next((p for p in self.thumbnails if p.asset_id == id), None)

    def on_asset_thumbnail_double_clicked(self, asset: dict):
        self.widget.show_asset_detail(asset)

    def on_edit_metadata(self, asset: dict):
        pass

    def on_save_metadata_changes(self, asset: dict):
        pass

    def _refresh_browser(self):
        if not self.widget.is_browser_visible():
            return
        self.widget.show_message(
            f"Refreshing browser...", "info", 2000)
        self.assets = self._load_assets()
        self.thumbnails = self._create_thumbnails_list(self.assets)
        self.widget.draw_thumbnails(self.thumbnails)
        self.widget.show_message(
            f"Browser refreshed!", "info", 2000)

    def _load_assets(self):
        return self.asset_service.get_assets()

    def _create_thumbnails_list(self, assets: list) -> List[Thumbnail]:
        """
        From a flat list of asset dicts, create a list of Thumbnail widgets.
        """
        thumbnails: List[Thumbnail] = []
        if not assets:
            return thumbnails

        for asset in assets:
            if not isinstance(asset, dict):
                continue

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

    def on_open_image_requested(self, asset: dict) -> None:
        print(f"Opening image for asset: {asset['name']}")
        self.widget.show_message(
            f"Opening image for asset: {asset['name']}", "info", 3000)
        if platform.system() == 'Darwin':
            subprocess.call(('open', asset['path']))
        elif platform.system() == 'Windows':
            os.startfile(asset['path'])

    def on_reveal_in_file_system_requested(self, asset: dict) -> None:
        print(f"Revealing in file system for asset: {asset['name']}")
        asset_path = pl.Path(asset['path'])
        if platform.system() == "Windows":
            os.startfile(str(asset_path.parent))
        elif platform.system() == "Darwin":
            subprocess.call(('open', str(asset_path.parent)))

    def on_instantiate_requested(self, asset: dict) -> None:
        print(f"Instantiating asset: {asset['name']}")
        self.instantiate_asset(asset)

    def on_replace_texture_requested(self, asset: dict) -> None:
        print(f"Replacing texture for asset: {asset['name']}")
        self.replace_texture(asset)

    def replace_texture(self, asset: dict) -> None:
        raise ImplementedByDerivedClassError(
            self.__class__.__name__, "replace_texture")

    def on_search_changed(self, text: str, delay: int = 200) -> None:
        if not hasattr(self, "_search_debounce_timer"):
            from PySide6.QtCore import QTimer
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
