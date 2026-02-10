"""Browser view for Universal Asset Browser."""

import sys
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    Qt,
    Signal,
    QSize,
    QTimer,
    QEvent,
    QModelIndex,
)
from PySide6.QtGui import QMouseEvent, QWheelEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListView,
    QLineEdit,
    QComboBox,
    QLabel,
    QProgressBar,
    QMenu,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QStackedWidget,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem

from uab.core.interfaces import Browsable
from uab.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    CompositeAsset,
    CompositeType,
    StandardAsset,
)
from uab.ui.composite_tree import CompositeTreeModel, CompositeTreeView, TreeItemDelegate
from uab.ui.delegates import AssetDelegate
from uab.ui.utils import load_hdri_thumbnail, LocalImageLoader

# Placeholder image path (relative to package)
_PLACEHOLDER_PATH = Path(
    __file__).parent.parent.parent.parent / "assets" / "model-placeholder.png"


class DetailView(QWidget):
    """
    Full-screen detail view for item inspection.

    Displays a large preview on the left and either:
    - A simple metadata panel for leaf assets
    - A recursive tree view for composite assets

    Emits signals for user interactions (back, import, download, expand).
    """

    back_clicked = Signal()
    import_clicked = Signal(str)  # item_id
    download_asset_clicked = Signal(str)  # asset_id
    download_composite_clicked = Signal(str, object)  # composite_id, resolution(str|None)
    tree_item_expanded = Signal(str)  # item_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailView")
        self._current_item: Browsable | None = None
        self._download_enabled = True
        self._preview_needs_load = False
        self._tree_model = CompositeTreeModel()
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left panel - Preview
        left_panel = QWidget()
        left_panel.setObjectName("detailLeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        # Back button at top
        self._back_btn = QPushButton("← Back")
        self._back_btn.setObjectName("backButton")
        self._back_btn.setMaximumWidth(100)
        self._back_btn.clicked.connect(self._on_back_clicked)
        left_layout.addWidget(self._back_btn)

        # Preview image
        self._preview_label = QLabel()
        self._preview_label.setObjectName("detailPreviewLarge")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setScaledContents(False)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        left_layout.addWidget(self._preview_label, 1)

        main_layout.addWidget(left_panel, 7)

        # Right panel - Metadata
        right_panel = QWidget()
        right_panel.setObjectName("detailRightPanel")
        right_panel.setMinimumWidth(320)
        right_panel.setMaximumWidth(450)

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(10)

        # Stacked detail panel (asset vs composite)
        self._detail_stack = QStackedWidget()

        # Page 0: Leaf asset details (metadata)
        asset_page = QWidget()
        asset_page_layout = QVBoxLayout(asset_page)
        asset_page_layout.setContentsMargins(0, 0, 0, 0)
        asset_page_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(20)

        name_section = self._create_field_section("Name")
        self._name_label = name_section["value"]
        self._name_label.setObjectName("detailNameLabel")
        content_layout.addLayout(name_section["layout"])
        content_layout.addWidget(self._create_separator())

        type_section = self._create_field_section("Type")
        self._type_label = type_section["value"]
        content_layout.addLayout(type_section["layout"])
        content_layout.addWidget(self._create_separator())

        status_section = self._create_field_section("Status")
        self._status_label = status_section["value"]
        content_layout.addLayout(status_section["layout"])
        content_layout.addWidget(self._create_separator())

        source_section = self._create_field_section("Source")
        self._source_label = source_section["value"]
        content_layout.addLayout(source_section["layout"])
        content_layout.addWidget(self._create_separator())

        author_section = self._create_field_section("Author")
        self._author_label = author_section["value"]
        content_layout.addLayout(author_section["layout"])
        content_layout.addWidget(self._create_separator())

        license_section = self._create_field_section("License")
        self._license_label = license_section["value"]
        content_layout.addLayout(license_section["layout"])
        content_layout.addWidget(self._create_separator())

        path_section = self._create_field_section("File Path")
        self._path_label = path_section["value"]
        self._path_label.setObjectName("detailPathLabel")
        self._path_container = path_section["layout"]
        content_layout.addLayout(self._path_container)
        content_layout.addWidget(self._create_separator())

        metadata_section = self._create_field_section("Details")
        self._metadata_label = metadata_section["value"]
        self._metadata_label.setMinimumHeight(60)
        content_layout.addLayout(metadata_section["layout"])
        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        asset_page_layout.addWidget(scroll_area, 1)

        # Page 1: Composite details (tree view)
        composite_page = QWidget()
        composite_layout = QVBoxLayout(composite_page)
        composite_layout.setContentsMargins(15, 15, 15, 15)
        composite_layout.setSpacing(10)

        self._composite_title = QLabel()
        self._composite_title.setObjectName("detailNameLabel")
        self._composite_title.setWordWrap(True)
        composite_layout.addWidget(self._composite_title)

        self._composite_status = QLabel()
        self._composite_status.setProperty("class", "fieldValue")
        self._composite_status.setWordWrap(True)
        composite_layout.addWidget(self._composite_status)

        self._warnings = QLabel()
        self._warnings.setWordWrap(True)
        self._warnings.setProperty("class", "fieldValue")
        self._warnings.setVisible(False)
        composite_layout.addWidget(self._warnings)

        composite_source_section = self._create_field_section("Source")
        self._composite_source_label = composite_source_section["value"]
        composite_layout.addLayout(composite_source_section["layout"])
        composite_layout.addWidget(self._create_separator())

        composite_author_section = self._create_field_section("Author")
        self._composite_author_label = composite_author_section["value"]
        composite_layout.addLayout(composite_author_section["layout"])
        composite_layout.addWidget(self._create_separator())

        composite_license_section = self._create_field_section("License")
        self._composite_license_label = composite_license_section["value"]
        composite_layout.addLayout(composite_license_section["layout"])
        composite_layout.addWidget(self._create_separator())

        self._tree = CompositeTreeView()
        self._tree.setObjectName("compositeTreeView")
        self._tree.setModel(self._tree_model)
        self._tree_delegate = TreeItemDelegate(self._tree)
        self._tree.setItemDelegate(self._tree_delegate)

        self._tree_delegate.download_clicked.connect(self.download_asset_clicked.emit)
        self._tree.item_expanded.connect(self.tree_item_expanded.emit)

        composite_layout.addWidget(self._tree, 1)

        self._detail_stack.addWidget(asset_page)
        self._detail_stack.addWidget(composite_page)

        right_layout.addWidget(self._detail_stack, 1)

        # Action buttons at bottom (shared)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._resolution_combo = QComboBox()
        self._resolution_combo.setObjectName("resolutionCombo")
        self._resolution_combo.addItems(["All", "1k", "2k", "4k", "8k"])
        self._resolution_combo.setVisible(False)
        btn_layout.addWidget(self._resolution_combo)

        self._download_btn = QPushButton("Download")
        self._download_btn.setObjectName("downloadButton")
        self._download_btn.clicked.connect(self._on_download_clicked)
        btn_layout.addWidget(self._download_btn)

        self._import_btn = QPushButton("Import")
        self._import_btn.setObjectName("primaryButton")
        self._import_btn.clicked.connect(self._on_import_clicked)
        btn_layout.addWidget(self._import_btn)

        right_layout.addLayout(btn_layout)

        main_layout.addWidget(right_panel, 3)

    def _create_field_section(self, label_text: str) -> dict:
        """Create a field section with label and value."""
        layout = QVBoxLayout()
        layout.setSpacing(5)

        label = QLabel(label_text)
        label.setProperty("class", "fieldLabel")

        value = QLabel()
        value.setWordWrap(True)
        value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        value.setProperty("class", "fieldValue")

        layout.addWidget(label)
        layout.addWidget(value)

        return {"layout": layout, "label": label, "value": value}

    def _create_separator(self) -> QFrame:
        """Create a horizontal separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        return sep

    def set_download_enabled(self, enabled: bool) -> None:
        """Enable or disable download capability."""
        self._download_enabled = enabled
        # refresh button visibility for current item
        if self._current_item is not None:
            self.show_item(self._current_item)

    def _get_metadata_dict(self, item: object) -> dict[str, Any]:
        """Safely read `item.metadata` as a dict."""
        meta = getattr(item, "metadata", None)
        return meta if isinstance(meta, dict) else {}

    def _format_author(self, meta: dict[str, Any]) -> str:
        """Format author display from flexible metadata payload."""
        author_any = meta.get("author")
        if isinstance(author_any, str) and author_any.strip():
            return author_any.strip()

        authors_any = meta.get("authors")
        if isinstance(authors_any, str) and authors_any.strip():
            return authors_any.strip()

        if isinstance(authors_any, dict):
            names = sorted(
                str(k).strip() for k in authors_any.keys() if str(k).strip()
            )
            return ", ".join(names) if names else "Unknown"

        if isinstance(authors_any, list):
            names = [a.strip() for a in authors_any if isinstance(a, str) and a.strip()]
            return ", ".join(names) if names else "Unknown"

        return "Unknown"

    def _format_license(self, meta: dict[str, Any]) -> str:
        """Format license display from flexible metadata payload."""
        license_any = meta.get("license")
        if isinstance(license_any, str) and license_any.strip():
            return license_any.strip()
        return "No license found"

    def show_item(self, item: Browsable) -> None:
        """
        Display the full details for an item (asset or composite).

        Args:
            item: The item to display
        """
        self._current_item = item
        self._preview_needs_load = True

        if isinstance(item, CompositeAsset):
            self._detail_stack.setCurrentIndex(1)
            self._resolution_combo.setVisible(True)
            self._download_btn.setText("Download All")

            self._composite_title.setText(item.name)
            status_text = item.display_status.value.upper()
            if item.is_mixed:
                status_text = "MIXED"
            self._composite_status.setText(f"Status: {status_text}")

            warnings = self._get_composite_warnings(item)
            self._warnings.setText("\n".join(warnings))
            self._warnings.setVisible(bool(warnings))

            self._composite_source_label.setText(item.source)
            meta = self._get_metadata_dict(item)
            self._composite_author_label.setText(self._format_author(meta))
            self._composite_license_label.setText(self._format_license(meta))

            self._tree_model.set_root(item)
            self._tree.expandToDepth(0)

            self._download_btn.setVisible(
                self._download_enabled and getattr(item, "has_cloud_children", False)
            )
            # gray out import if nothing is local
            self._import_btn.setEnabled(getattr(item, "has_local_children", False))

        else:
            self._detail_stack.setCurrentIndex(0)
            self._resolution_combo.setVisible(False)
            self._download_btn.setText("Download")

            item_type = getattr(item, "type", None)
            if item_type is None and hasattr(item, "asset_type"):
                item_type = getattr(item, "asset_type", None)

            status = getattr(item, "status", item.display_status)
            self._name_label.setText(item.name)
            self._type_label.setText(
                item_type.value.upper() if isinstance(item_type, AssetType) else "UNKNOWN"
            )
            self._status_label.setText(
                status.value.upper() if isinstance(status, AssetStatus) else "UNKNOWN"
            )
            self._source_label.setText(item.source)
            meta = self._get_metadata_dict(item)
            self._author_label.setText(self._format_author(meta))
            self._license_label.setText(self._format_license(meta))

            local_path = getattr(item, "local_path", None)
            if local_path:
                self._path_label.setText(str(local_path))
            else:
                self._path_label.setText("Not downloaded")

            self._metadata_label.setText(self._format_asset_metadata(item))

            self._download_btn.setVisible(
                bool(status == AssetStatus.CLOUD and self._download_enabled)
            )
            self._import_btn.setEnabled(bool(status == AssetStatus.LOCAL))

        # Defer preview loading until widget is shown and laid out
        QTimer.singleShot(0, self._deferred_load_preview)

    def _deferred_load_preview(self) -> None:
        """Load preview after widget is laid out."""
        if self._current_item and self._preview_needs_load:
            self._load_preview(self._current_item)
            self._preview_needs_load = False

    def _load_preview(self, item: Browsable) -> None:
        """Load the preview image for the current item."""
        pixmap = QPixmap()

        # Try thumbnail_path first
        thumb_path = getattr(item, "thumbnail_path", None)
        if thumb_path and thumb_path.exists():
            pixmap.load(str(thumb_path))

        # Try local_path for various formats
        local_path = getattr(item, "local_path", None)
        if pixmap.isNull() and local_path and local_path.exists():
            suffix = local_path.suffix.lower()
            if suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                pixmap.load(str(local_path))
            elif suffix in (".hdr", ".exr"):
                # Use HDR loader for high dynamic range images
                # Use a larger max_size for the detail view
                hdri_pixmap = load_hdri_thumbnail(
                    local_path, max_size=1024)
                if hdri_pixmap:
                    pixmap = hdri_pixmap

        if pixmap.isNull() and _PLACEHOLDER_PATH.exists():
            pixmap.load(str(_PLACEHOLDER_PATH))

        if not pixmap.isNull():
            available_width = self._preview_label.width() - 40
            available_height = self._preview_label.height() - 40

            # Use reasonable defaults if widget not yet sized
            if available_width < 100:
                available_width = 600
            if available_height < 100:
                available_height = 400

            scaled = pixmap.scaled(
                available_width,
                available_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview_label.setPixmap(scaled)
            self._preview_label.setProperty("noPreview", False)
        else:
            self._preview_label.setText("Preview not available")
            self._preview_label.setProperty("noPreview", True)

        # Refresh styling
        self._preview_label.style().unpolish(self._preview_label)
        self._preview_label.style().polish(self._preview_label)

    def showEvent(self, event: QShowEvent) -> None:
        """Handle show event to load preview when widget becomes visible."""
        super().showEvent(event)
        # Reload preview when shown (in case size changed)
        if self._current_item:
            QTimer.singleShot(50, self._deferred_load_preview)

    def resizeEvent(self, event) -> None:
        """Handle resize to update preview scaling."""
        super().resizeEvent(event)
        if self._current_item and self.isVisible():
            # Debounce resize updates
            self._preview_needs_load = True
            QTimer.singleShot(100, self._deferred_load_preview)

    def _on_back_clicked(self) -> None:
        """Handle back button click."""
        self.back_clicked.emit()

    def _on_download_clicked(self) -> None:
        """Handle download button click."""
        if not self._current_item:
            return

        if isinstance(self._current_item, CompositeAsset):
            resolution_text = self._resolution_combo.currentText()
            resolution: str | None = None if resolution_text == "All" else resolution_text
            self.download_composite_clicked.emit(self._current_item.id, resolution)
        else:
            self.download_asset_clicked.emit(self._current_item.id)

    def _on_import_clicked(self) -> None:
        """Handle import button click."""
        if self._current_item:
            self.import_clicked.emit(self._current_item.id)

    def _format_asset_metadata(self, item: Browsable) -> str:
        meta = getattr(item, "metadata", None)
        if not isinstance(meta, dict) or not meta:
            return "No additional details"

        parts: list[str] = []
        for key in ("resolution", "map_type", "format", "role"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                parts.append(f"{key.replace('_', ' ').title()}: {value}")

        file_size = getattr(item, "file_size", None)
        if isinstance(file_size, int):
            parts.append(f"File Size: {file_size} bytes")

        remote_url = getattr(item, "remote_url", None)
        if isinstance(remote_url, str) and remote_url:
            parts.append("Remote: yes")

        return "\n".join(parts) if parts else "No additional details"

    def _get_composite_warnings(self, composite: CompositeAsset) -> list[str]:
        warnings: list[str] = []
        if not composite.children:
            warnings.append("This composite has no loaded children yet.")
            return warnings

        if composite.has_cloud_children:
            warnings.append("Some items are still in the cloud.")
        if not composite.has_local_children:
            warnings.append("Nothing is downloaded yet. Import is disabled.")
        return warnings


class BrowserView(QWidget):
    """
    Main browser widget containing search, grid view, and full-screen detail view.

    This is a "dumb" view that emits signals for user interactions.
    The presenter handles all business logic.

    Signals:
        search_requested: Debounced search query
        filter_changed: Filter selection changed
        detail_requested: User double-clicked an asset
        import_requested: User requested import via context menu
        download_requested: User requested download via context menu
        remove_requested: User requested removal via context menu
    """
    # TODO: port hover preview window effect from the prototype

    search_requested = Signal(str)  # search query
    filter_changed = Signal(str)  # filter type
    detail_requested = Signal(str)  # item_id
    import_requested = Signal(str)  # item_id
    # back-compat: some presenters connect to this single-signal download API
    download_requested = Signal(str)  # item_id
    # separate download signals for assets vs composites
    download_asset_requested = Signal(str)  # asset_id
    download_composite_requested = Signal(str, object)  # composite_id, resolution(str|None)
    tree_item_expanded = Signal(str)  # item_id
    remove_requested = Signal(str)  # item_id
    add_files_requested = Signal()  # request to add individual files
    add_folder_requested = Signal()  # request to add folder
    # asset_id - create new node (Cmd/Ctrl+Click)
    new_asset_requested = Signal(str)
    # asset_id - replace selected node (Opt/Alt+Click)
    replace_asset_requested = Signal(str)

    # Thumbnail base size and zoom constraints
    _BASE_CELL_SIZE = 180
    _MIN_SCALE = 0.3
    _MAX_SCALE = 2.74

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("browserView")

        self._scale_factor = 1.0
        self._download_enabled = True
        self._remove_enabled = True
        self._items: dict[str, Browsable] = {}  # Cache by item ID (grid only)
        self._current_hover_index: Optional[QModelIndex] = None
        self._current_detail_item: Browsable | None = None

        # Host-specific action configuration
        self._replace_enabled = False
        self._get_node_label: Callable[[
            AssetType], str] = lambda t: t.value.title()

        # for loading HDR and EXR files that don't have a pre-rendered thumbnail
        self._image_loader = LocalImageLoader(self)

        self._init_ui()
        self._setup_connections()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Stacked widget to switch between grid and detail views
        self._stack = QStackedWidget()

        # Page 0: Grid view container (toolbar + grid + progress bar)
        grid_container = QWidget()
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setSpacing(0)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        self._toolbar = self._create_toolbar()
        grid_layout.addWidget(self._toolbar)

        # Grid view
        self._grid = self._create_grid_view()
        grid_layout.addWidget(self._grid, 1)

        # Progress bar (hidden by default)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(20)
        grid_layout.addWidget(self._progress_bar)

        # Loading indicator
        self._loading_label = QLabel("Loading...")
        self._loading_label.setObjectName("loadingIndicator")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setVisible(False)

        self._stack.addWidget(grid_container)

        # Page 1: Detail view (full-screen)
        self._detail_view = DetailView()
        self._detail_view.back_clicked.connect(self.hide_detail)
        self._detail_view.import_clicked.connect(self.import_requested.emit)
        # detail download signals
        self._detail_view.download_asset_clicked.connect(
            self.download_asset_requested.emit
        )
        self._detail_view.download_composite_clicked.connect(
            self.download_composite_requested.emit
        )
        self._detail_view.tree_item_expanded.connect(self.tree_item_expanded.emit)
        self._stack.addWidget(self._detail_view)

        main_layout.addWidget(self._stack)

    def _create_toolbar(self) -> QWidget:
        """Create the toolbar with search and filter controls."""
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar.setFixedHeight(50)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)

        # Search bar with debounce
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search assets by name...")
        self._search_bar.setMinimumWidth(250)
        self._search_bar.setClearButtonEnabled(True)

        # Debounce timer
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)

        # Filter combo
        filter_label = QLabel("Filter:")
        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(120)
        self._filter_combo.addItems([
            "All Assets",
            "HDRIs",
            "Textures",
            "Materials",
            "Models",
        ])

        # Renderer combo (populated by presenter)
        renderer_label = QLabel("Renderer:")
        self._renderer_combo = QComboBox()
        self._renderer_combo.setMinimumWidth(120)

        # Add Files button (hidden by default, enabled by presenter for local plugin)
        self._add_files_btn = QPushButton("Add Files")
        self._add_files_btn.setObjectName("addFilesButton")
        self._add_files_btn.setVisible(False)
        self._add_files_btn.clicked.connect(self.add_files_requested.emit)

        # Add Folder button (hidden by default, enabled by presenter for local plugin)
        self._add_folder_btn = QPushButton("Add Folder")
        self._add_folder_btn.setObjectName("addFolderButton")
        self._add_folder_btn.setVisible(False)
        self._add_folder_btn.clicked.connect(self.add_folder_requested.emit)

        layout.addWidget(self._search_bar, 1)
        layout.addWidget(filter_label)
        layout.addWidget(self._filter_combo)
        layout.addWidget(renderer_label)
        layout.addWidget(self._renderer_combo)
        layout.addWidget(self._add_files_btn)
        layout.addWidget(self._add_folder_btn)
        layout.addStretch()

        return toolbar

    def _create_grid_view(self) -> QListView:
        """Create the grid view for displaying assets."""
        grid = QListView()
        grid.setViewMode(QListView.ViewMode.IconMode)
        grid.setResizeMode(QListView.ResizeMode.Adjust)
        grid.setUniformItemSizes(True)
        grid.setSpacing(10)
        grid.setSelectionMode(QListView.SelectionMode.SingleSelection)
        grid.setMovement(QListView.Movement.Static)
        grid.setWrapping(True)
        grid.setWordWrap(True)

        # Enable mouse tracking for hover effects
        grid.setMouseTracking(True)
        grid.viewport().setMouseTracking(True)

        # Set icon size based on scale
        size = int(self._BASE_CELL_SIZE * self._scale_factor)
        grid.setIconSize(QSize(size, size))
        grid.setGridSize(QSize(size + 20, size + 40))

        # Model and delegate
        self._model = QStandardItemModel()
        grid.setModel(self._model)

        self._delegate = AssetDelegate()
        self._delegate.set_preview_parent(grid.viewport())
        self._delegate.set_image_loader(self._image_loader)
        grid.setItemDelegate(self._delegate)

        grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # event filter for Ctrl+wheel zoom
        grid.viewport().installEventFilter(self)

        return grid

    def _setup_connections(self) -> None:
        """Connect internal signals and slots."""
        self._search_bar.textChanged.connect(self._on_search_text_changed)
        # debounce search
        self._search_timer.timeout.connect(self._emit_search)

        self._filter_combo.currentTextChanged.connect(self.filter_changed.emit)

        self._grid.doubleClicked.connect(self._on_item_double_clicked)
        self._grid.customContextMenuRequested.connect(self._show_context_menu)

        self._delegate.thumbnail_ready.connect(self._on_thumbnail_ready)

    # PUBLIC API

    def set_items(self, items: list[Browsable]) -> None:
        """
        Update the grid with new items.

        Args:
            items: List of Browsable items to display
        """
        self._model.clear()
        self._items.clear()

        if not items:
            self._show_empty_state()
            return

        for it in items:
            row_item = QStandardItem()
            row_item.setData(it, Qt.ItemDataRole.UserRole)
            row_item.setData(it.name, Qt.ItemDataRole.DisplayRole)
            row_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self._model.appendRow(row_item)
            self._items[it.id] = it

    def set_download_enabled(self, enabled: bool) -> None:
        """Enable or disable download capability."""
        self._download_enabled = enabled
        self._detail_view.set_download_enabled(enabled)

    def set_remove_enabled(self, enabled: bool) -> None:
        """Enable or disable remove capability."""
        self._remove_enabled = enabled

    def set_add_assets_enabled(self, enabled: bool) -> None:
        """Show or hide the Add Files and Add Folder buttons."""
        self._add_files_btn.setVisible(enabled)
        self._add_folder_btn.setVisible(enabled)

    def set_host_actions(
        self,
        replace_enabled: bool,
        get_label: Callable[[AssetType], str] | None = None,
    ) -> None:
        """
        Configure host-specific context menu actions.

        Args:
            replace_enabled: Whether the "Replace" action should be shown
                (only available in hosts that support node selection)
            get_label: Callable that returns a label for an asset type
                (e.g., "Environment Light" for HDRI). If None, uses default labels.
        """
        self._replace_enabled = replace_enabled
        self._get_node_label = get_label or (lambda t: t.value.title())

    def set_loading(self, loading: bool) -> None:
        """Show or hide the loading indicator."""
        self._loading_label.setVisible(loading)
        self._grid.setVisible(not loading)

    def set_download_progress(self, asset_id: str, progress: float) -> None:
        """
        Update download progress for an asset.

        Args:
            asset_id: The asset being downloaded
            progress: Progress value from 0.0 to 1.0
        """
        if progress < 0:
            self._progress_bar.setVisible(False)
        else:
            self._progress_bar.setVisible(True)
            self._progress_bar.setValue(int(progress * 100))
            if progress >= 1.0:
                QTimer.singleShot(
                    1000, lambda: self._progress_bar.setVisible(False))

    def set_renderers(self, renderers: list[str]) -> None:
        """
        Populate the renderer combo box.

        Args:
            renderers: List of renderer names
        """
        self._renderer_combo.clear()
        self._renderer_combo.addItems(renderers)

    def get_selected_renderer(self) -> str:
        """Return the currently selected renderer."""
        return self._renderer_combo.currentText()

    def get_current_filter(self) -> str:
        """Return the currently selected filter."""
        return self._filter_combo.currentText()

    def show_detail(self, item: Browsable) -> None:
        """
        Display the full-screen detail view for an item.

        Args:
            item: The item to display details for
        """
        # Hide preview popup when switching to detail view
        self._delegate.hide_preview()
        self._current_hover_index = None

        self._current_detail_item = item
        self._detail_view.show_item(item)
        self._stack.setCurrentIndex(1)

    def hide_detail(self) -> None:
        """Hide the detail view and return to grid."""
        self._stack.setCurrentIndex(0)
        self._current_detail_item = None

    def is_detail_visible(self) -> bool:
        """Check if the detail view is currently shown."""
        return self._stack.currentIndex() == 1

    # INTERNAL METHODS

    def _on_thumbnail_ready(self, asset_id: str) -> None:
        """
        Handle thumbnail ready signal from delegate.

        Finds the item index and triggers a repaint for that item.

        Args:
            asset_id: The asset ID whose thumbnail is ready
        """
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            asset = index.data(Qt.ItemDataRole.UserRole)
            if asset and asset.id == asset_id:
                self._grid.update(index)
                break

    def _show_empty_state(self) -> None:
        """Display empty state placeholder."""
        # Add a single item that shows the empty state
        item = QStandardItem()
        item.setData(None, Qt.ItemDataRole.UserRole)
        item.setData("No assets to display", Qt.ItemDataRole.DisplayRole)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._model.appendRow(item)

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search text change - start debounce timer."""
        self._search_timer.stop()
        self._search_timer.start()

    def _emit_search(self) -> None:
        """Emit the search request after debounce."""
        self.search_requested.emit(self._search_bar.text())

    def _on_item_double_clicked(self, index) -> None:
        """Handle double-click on grid item."""
        item = index.data(Qt.ItemDataRole.UserRole)
        if item:
            self.detail_requested.emit(item.id)

    def _show_context_menu(self, pos) -> None:
        """Show context menu for the item at position."""
        # Hide preview popup when showing context menu
        self._delegate.hide_preview()
        self._current_hover_index = None

        index = self._grid.indexAt(pos)
        if not index.isValid():
            return

        item: Browsable = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            return

        menu = QMenu(self)

        # Platform-specific hotkey hints
        is_mac = sys.platform == "darwin"
        cmd_hint = "⌘ Click" if is_mac else "Ctrl+Click"
        alt_hint = "⌥ Click" if is_mac else "Alt+Click"

        # Composite context menu
        if isinstance(item, CompositeAsset):
            if self._download_enabled and getattr(item, "has_cloud_children", False):
                download_action = menu.addAction("Download All")
                download_action.triggered.connect(
                    lambda: self.download_composite_requested.emit(item.id, None)
                )

            import_action = menu.addAction("Import")
            import_action.setEnabled(getattr(item, "has_local_children", False))
            import_action.triggered.connect(lambda: self.import_requested.emit(item.id))

            menu.addSeparator()
            details_action = menu.addAction("View Details")
            details_action.triggered.connect(
                lambda: self.detail_requested.emit(item.id)
            )

            menu.exec(self._grid.viewport().mapToGlobal(pos))
            return

        # Leaf asset context menu
        status = getattr(item, "status", item.display_status)
        asset_type = getattr(item, "type", None)
        if asset_type is None and hasattr(item, "asset_type"):
            asset_type = getattr(item, "asset_type", None)

        node_label = (
            self._get_node_label(asset_type)
            if isinstance(asset_type, AssetType)
            else "Asset"
        )

        # Status-dependent actions
        if status == AssetStatus.CLOUD:
            if self._download_enabled:
                download_action = menu.addAction("Download")
                download_action.triggered.connect(
                    lambda: self.download_asset_requested.emit(item.id)
                )

            import_action = menu.addAction("Import (will download first)")
            import_action.triggered.connect(
                lambda: self.import_requested.emit(item.id)
            )

        elif status == AssetStatus.LOCAL:
            # New <asset> action with hotkey hint
            new_action = menu.addAction(f"New {node_label}\t{cmd_hint}")
            new_action.triggered.connect(
                lambda: self.new_asset_requested.emit(item.id)
            )

            # Replace <asset> action (only if host supports it)
            if self._replace_enabled:
                replace_action = menu.addAction(
                    f"Replace {node_label}\t{alt_hint}")
                replace_action.triggered.connect(
                    lambda: self.replace_asset_requested.emit(item.id)
                )

            if self._remove_enabled:
                menu.addSeparator()
                remove_action = menu.addAction("Remove")
                remove_action.triggered.connect(
                    lambda: self.remove_requested.emit(item.id)
                )

        elif status == AssetStatus.DOWNLOADING:
            downloading_action = menu.addAction("Downloading...")
            downloading_action.setEnabled(False)

        menu.addSeparator()
        details_action = menu.addAction("View Details")
        details_action.triggered.connect(
            lambda: self.detail_requested.emit(item.id)
        )

        menu.exec(self._grid.viewport().mapToGlobal(pos))

    def _handle_modifier_click(self, event: QMouseEvent) -> bool:
        """
        Handle modifier+click hotkeys for quick actions.

        Hotkeys:
        - macOS: Cmd+Click (New), Opt+Click (Replace)
        - Windows/Linux: Ctrl+Click (New), Alt+Click (Replace)

        Args:
            event: The mouse event

        Returns:
            True if the event was handled, False otherwise
        """
        modifiers = event.modifiers()
        pos = event.pos()
        index = self._grid.indexAt(pos)

        if not index.isValid():
            return False

        item: Browsable = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            return False

        # Only handle local assets (can't create/replace with cloud assets directly)
        if not isinstance(item, (Asset, StandardAsset)):
            return False
        if item.status != AssetStatus.LOCAL:
            return False

        # Qt swaps Ctrl/Meta on macOS by default, so ControlModifier maps to:
        # - macOS: Command key (⌘)
        # - Windows/Linux: Ctrl key
        # This gives us consistent cross-platform behavior.

        # Cmd/Ctrl+Click: New asset
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._delegate.hide_preview()
            self.new_asset_requested.emit(item.id)
            return True

        # Opt/Alt+Click: Replace asset (only if enabled)
        if modifiers & Qt.KeyboardModifier.AltModifier and self._replace_enabled:
            self._delegate.hide_preview()
            self.replace_asset_requested.emit(item.id)
            return True

        return False

    def _handle_zoom(self, event: QWheelEvent) -> None:
        """Handle Ctrl+wheel zoom."""
        # Hide preview when zooming as item positions change
        self._delegate.hide_preview()
        self._current_hover_index = None

        delta = event.angleDelta().y() / 240.0
        factor_change = 1.0 + delta * 0.2
        new_scale = max(
            self._MIN_SCALE,
            min(self._scale_factor * factor_change, self._MAX_SCALE)
        )

        if new_scale != self._scale_factor:
            self._scale_factor = new_scale
            new_size = int(self._BASE_CELL_SIZE * self._scale_factor)
            self._grid.setIconSize(QSize(new_size, new_size))
            self._grid.setGridSize(QSize(new_size + 20, new_size + 40))
            self._delegate.set_cell_size(new_size)

    def eventFilter(self, obj, event: QEvent) -> bool:
        """Filter events for modifier+click, Ctrl+wheel zoom, and hover tracking."""
        if obj == self._grid.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event: QMouseEvent = event
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    # Check for modifier+click hotkeys
                    handled = self._handle_modifier_click(mouse_event)
                    if handled:
                        return True
            elif event.type() == QEvent.Type.Wheel:
                wheel_event: QWheelEvent = event
                if wheel_event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._handle_zoom(wheel_event)
                    return True
                else:
                    # Hide preview on regular scroll as item positions change
                    self._delegate.hide_preview()
                    self._current_hover_index = None
            elif event.type() == QEvent.Type.MouseMove:
                # Track hover for delegate and preview popup
                pos = event.pos()
                index = self._grid.indexAt(pos)

                if index.isValid():
                    self._delegate.set_hovered_index(index)

                    # Check if we moved to a different item
                    if (
                        self._current_hover_index is None
                        or self._current_hover_index != index
                    ):
                        # Left previous item
                        if self._current_hover_index is not None:
                            self._delegate.on_item_hover_leave()

                        # Entered new item
                        self._current_hover_index = index
                        item_rect = self._grid.visualRect(index)
                        global_pos = self._grid.viewport().mapToGlobal(pos)
                        self._delegate.on_item_hover_enter(
                            index, item_rect, global_pos
                        )
                else:
                    self._delegate.set_hovered_index(None)
                    # Left item area
                    if self._current_hover_index is not None:
                        self._delegate.on_item_hover_leave()
                        self._current_hover_index = None

                self._grid.viewport().update()
            elif event.type() == QEvent.Type.Leave:
                # Clear hover when mouse leaves viewport
                self._delegate.set_hovered_index(None)
                if self._current_hover_index is not None:
                    self._delegate.on_item_hover_leave()
                    self._current_hover_index = None
                self._grid.viewport().update()
        return super().eventFilter(obj, event)
