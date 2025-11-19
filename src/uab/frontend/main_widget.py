from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QStackedWidget,
)
from uab.core.desktop_presenter import DesktopPresenter
from uab.core.houdini_presenter import HoudiniPresenter
from uab.frontend.browser import Browser
from uab.frontend.detail import Detail
from uab.frontend.thumbnail import Thumbnail
from uab.frontend.toolbar import Toolbar
from uab.frontend.status_bar import StatusBar


class MainWidget(QWidget):
    """
    Central widget containing the full UI layout of the Universal Asset Browser.
    """

    search_text_changed = Signal(str)
    filter_changed = Signal(str)
    renderer_changed = Signal(str)
    import_clicked = Signal(str)
    back_clicked = Signal()
    delete_asset_clicked = Signal(int)
    widget_closed = Signal()
    save_metadata_changes_clicked = Signal(dict)

    def __init__(self, dcc: str, client_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client_id = client_id
        self.current_asset = None
        self.current_thumbnails = []

        # Root layout
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar at top
        self.toolbar = Toolbar()
        self.toolbar.search_text_changed.connect(self._on_search_changed)
        self.toolbar.filter_changed.connect(self._on_filter_changed)
        self.layout.addWidget(self.toolbar)

        # Main Splitter
        self.main_splitter = QSplitter()

        # Stacked (browser/detail)
        self.stacked = QStackedWidget()
        self.browser = Browser()
        self.detail = Detail()
        self.stacked.addWidget(self.browser)
        self.stacked.addWidget(self.detail)
        self.main_splitter.addWidget(self.stacked)

        # Configure split sizes, collapsibility
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setSizes([1200])

        self.layout.addWidget(self.main_splitter)

        # Status bar at bottom
        self.status_bar = StatusBar()
        self.layout.addWidget(self.status_bar)

        self.status_bar.setStyleSheet(self.status_bar.styleSheet())
        self.status_bar.update()

        # Connections
        self.detail.back_clicked.connect(self._on_back_clicked)
        self.detail.delete_clicked.connect(self._on_delete_asset_clicked)
        self.detail.save_clicked.connect(self._on_save_metadata_changes)
        self.toolbar.import_asset_selected.connect(self._on_import_clicked)
        self.toolbar.renderer_changed.connect(self._on_renderer_changed)

        match dcc:
            case "hou":
                self.presenter = HoudiniPresenter(self)
            case "desktop":
                self.presenter = DesktopPresenter(self)
            case _:
                raise ValueError(f"Invalid DCC: {dcc}")

    def _on_save_metadata_changes(self, asset: dict) -> None:
        self.save_metadata_changes_clicked.emit(asset)

    def _on_back_clicked(self) -> None:
        self.back_clicked.emit()

    def show_browser(self) -> None:
        self.stacked.setCurrentWidget(self.browser)

    def show_asset_detail(self, asset: dict) -> None:
        self.stacked.setCurrentWidget(self.detail)
        self.detail.draw_details(asset)

    def is_browser_visible(self) -> bool:
        return self.stacked.currentWidget() == self.browser

    def is_detail_visible(self) -> bool:
        return self.stacked.currentWidget() == self.detail

    def show_message(
        self, msg: str, message_type: str = "info", timeout: int = 5000
    ) -> None:
        self.status_bar.show_message(msg, message_type, timeout)

    def _on_search_changed(self, text: str) -> None:
        self.search_text_changed.emit(text)

    def _on_filter_changed(self, filter_text: str) -> None:
        self.filter_changed.emit(filter_text)

    def _on_renderer_changed(self, renderer_text: str) -> None:
        self.renderer_changed.emit(renderer_text)

    def _on_import_clicked(self, asset_path: str) -> None:
        self.import_clicked.emit(asset_path)

    def _on_delete_asset_clicked(self, asset_id: int) -> None:
        self.delete_asset_clicked.emit(asset_id)

    def set_current_asset(self, asset: dict) -> None:
        self.current_asset = asset

    def draw_thumbnails(self, thumbnails: list[Thumbnail]) -> None:
        self.current_thumbnails = thumbnails
        self.browser.refresh_thumbnails(thumbnails)

    def set_new_selected_thumbnail(self, thumbnail: Thumbnail) -> Thumbnail:
        if thumbnail.is_selected:
            thumbnail.set_selected(False)
            return thumbnail
        for p in self.current_thumbnails:
            if p.asset_id != thumbnail.asset_id:
                p.set_selected(False)
        thumbnail.set_selected(True)
        return thumbnail

    def closeEvent(self, event: QCloseEvent) -> None:
        self.widget_closed.emit()
        super().closeEvent(event)
