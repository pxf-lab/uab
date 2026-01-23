"""Browser view for Universal Asset Browser."""

import sys
from pathlib import Path
from typing import Callable, Optional

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

from uab.core.models import AssetType, StandardAsset, AssetStatus
from uab.ui.delegates import AssetDelegate
from uab.ui.utils import load_hdri_thumbnail

# Placeholder image path (relative to package)
_PLACEHOLDER_PATH = Path(
    __file__).parent.parent.parent.parent / "assets" / "model-placeholder.png"


class DetailView(QWidget):
    """
    Full-screen detail view for asset inspection.

    Displays a large preview on the left and metadata on the right.
    Emits signals for user interactions (back, import, download).
    """

    back_clicked = Signal()
    import_clicked = Signal(str)  # asset_id
    download_clicked = Signal(str)  # asset_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailView")
        self._current_asset: Optional[StandardAsset] = None
        self._download_enabled = True
        self._preview_needs_load = False
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
        right_layout.setSpacing(0)

        # Scroll area for metadata
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(20)

        # Name field
        name_section = self._create_field_section("Name")
        self._name_label = name_section["value"]
        self._name_label.setObjectName("detailNameLabel")
        content_layout.addLayout(name_section["layout"])

        content_layout.addWidget(self._create_separator())

        # Type field
        type_section = self._create_field_section("Type")
        self._type_label = type_section["value"]
        content_layout.addLayout(type_section["layout"])

        content_layout.addWidget(self._create_separator())

        # Status field
        status_section = self._create_field_section("Status")
        self._status_label = status_section["value"]
        content_layout.addLayout(status_section["layout"])

        content_layout.addWidget(self._create_separator())

        # Source field
        source_section = self._create_field_section("Source")
        self._source_label = source_section["value"]
        content_layout.addLayout(source_section["layout"])

        content_layout.addWidget(self._create_separator())

        # Path field
        path_section = self._create_field_section("File Path")
        self._path_label = path_section["value"]
        self._path_label.setObjectName("detailPathLabel")
        self._path_container = path_section["layout"]
        content_layout.addLayout(self._path_container)

        content_layout.addWidget(self._create_separator())

        # Metadata section (for additional info like resolutions, files)
        metadata_section = self._create_field_section("Details")
        self._metadata_label = metadata_section["value"]
        self._metadata_label.setMinimumHeight(60)
        content_layout.addLayout(metadata_section["layout"])

        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        right_layout.addWidget(scroll_area, 1)

        # Action buttons at bottom
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

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

    def show_asset(self, asset: StandardAsset) -> None:
        """
        Display the full details for an asset.

        Args:
            asset: The asset to display
        """
        self._current_asset = asset
        self._preview_needs_load = True

        # Update labels
        self._name_label.setText(asset.name)
        self._type_label.setText(asset.type.value.upper())
        self._status_label.setText(asset.status.value.upper())
        self._source_label.setText(asset.source)

        # Path (only show if local)
        if asset.local_path:
            self._path_label.setText(str(asset.local_path))
            self._path_label.setVisible(True)
        else:
            self._path_label.setText("Not downloaded")
            self._path_label.setVisible(True)

        # Build metadata display
        metadata_parts = []
        if asset.metadata:
            if "resolutions" in asset.metadata:
                resolutions = asset.metadata["resolutions"]
                if isinstance(resolutions, list):
                    metadata_parts.append(
                        f"Resolutions: {', '.join(resolutions)}")
            if "files" in asset.metadata:
                files = asset.metadata["files"]
                if isinstance(files, dict):
                    metadata_parts.append(f"Files: {len(files)}")
            if "author" in asset.metadata:
                metadata_parts.append(f"Author: {asset.metadata['author']}")
            if "categories" in asset.metadata:
                cats = asset.metadata["categories"]
                if isinstance(cats, list):
                    metadata_parts.append(f"Categories: {', '.join(cats)}")

        self._metadata_label.setText(
            "\n".join(
                metadata_parts) if metadata_parts else "No additional details"
        )

        # Update button states
        self._download_btn.setVisible(
            asset.status == AssetStatus.CLOUD and self._download_enabled
        )
        self._import_btn.setEnabled(asset.status == AssetStatus.LOCAL)

        # Defer preview loading until widget is shown and laid out
        QTimer.singleShot(0, self._deferred_load_preview)

    def _deferred_load_preview(self) -> None:
        """Load preview after widget is laid out."""
        if self._current_asset and self._preview_needs_load:
            self._load_preview(self._current_asset)
            self._preview_needs_load = False

    def _load_preview(self, asset: StandardAsset) -> None:
        """Load the preview image for the asset."""
        pixmap = QPixmap()

        # Try thumbnail_path first
        if asset.thumbnail_path and asset.thumbnail_path.exists():
            pixmap.load(str(asset.thumbnail_path))

        # Try local_path for various formats
        if pixmap.isNull() and asset.local_path and asset.local_path.exists():
            suffix = asset.local_path.suffix.lower()
            if suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                pixmap.load(str(asset.local_path))
            elif suffix in (".hdr", ".exr"):
                # Use HDR loader for high dynamic range images
                # Use a larger max_size for the detail view
                hdri_pixmap = load_hdri_thumbnail(
                    asset.local_path, max_size=1024)
                if hdri_pixmap:
                    pixmap = hdri_pixmap

        # Fall back to placeholder if no image loaded
        if pixmap.isNull() and _PLACEHOLDER_PATH.exists():
            pixmap.load(str(_PLACEHOLDER_PATH))

        if not pixmap.isNull():
            # Get available space for preview
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
        if self._current_asset:
            QTimer.singleShot(50, self._deferred_load_preview)

    def resizeEvent(self, event) -> None:
        """Handle resize to update preview scaling."""
        super().resizeEvent(event)
        if self._current_asset and self.isVisible():
            # Debounce resize updates
            self._preview_needs_load = True
            QTimer.singleShot(100, self._deferred_load_preview)

    def _on_back_clicked(self) -> None:
        """Handle back button click."""
        self.back_clicked.emit()

    def _on_download_clicked(self) -> None:
        """Handle download button click."""
        if self._current_asset:
            self.download_clicked.emit(self._current_asset.id)

    def _on_import_clicked(self) -> None:
        """Handle import button click."""
        if self._current_asset:
            self.import_clicked.emit(self._current_asset.id)


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
    detail_requested = Signal(str)  # asset_id
    import_requested = Signal(str)  # asset_id
    download_requested = Signal(str)  # asset_id
    remove_requested = Signal(str)  # asset_id
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
        self._assets: dict[str, StandardAsset] = {}  # Cache by asset ID
        self._current_hover_index: Optional[QModelIndex] = None

        # Host-specific action configuration
        self._replace_enabled = False
        self._get_node_label: Callable[[
            AssetType], str] = lambda t: t.value.title()

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
        self._detail_view.download_clicked.connect(
            self.download_requested.emit)
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
        grid.setItemDelegate(self._delegate)

        # Context menu
        grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Install event filter for Ctrl+wheel zoom
        grid.viewport().installEventFilter(self)

        return grid

    def _setup_connections(self) -> None:
        """Connect internal signals and slots."""
        # Search with debounce
        self._search_bar.textChanged.connect(self._on_search_text_changed)
        self._search_timer.timeout.connect(self._emit_search)

        # Filter
        self._filter_combo.currentTextChanged.connect(self.filter_changed.emit)

        # Grid interactions
        self._grid.doubleClicked.connect(self._on_item_double_clicked)
        self._grid.customContextMenuRequested.connect(self._show_context_menu)

    # PUBLIC API

    def set_items(self, assets: list[StandardAsset]) -> None:
        """
        Update the grid with new assets.

        Args:
            assets: List of StandardAsset objects to display
        """
        self._model.clear()
        self._assets.clear()

        if not assets:
            self._show_empty_state()
            return

        for asset in assets:
            item = QStandardItem()
            item.setData(asset, Qt.ItemDataRole.UserRole)
            item.setData(asset.name, Qt.ItemDataRole.DisplayRole)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self._model.appendRow(item)
            self._assets[asset.id] = asset

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

    def show_detail(self, asset: StandardAsset) -> None:
        """
        Display the full-screen detail view for an asset.

        Args:
            asset: The asset to display details for
        """
        # Hide preview popup when switching to detail view
        self._delegate.hide_preview()
        self._current_hover_index = None

        self._current_detail_asset = asset
        self._detail_view.show_asset(asset)
        self._stack.setCurrentIndex(1)

    def hide_detail(self) -> None:
        """Hide the detail view and return to grid."""
        self._stack.setCurrentIndex(0)
        self._current_detail_asset = None

    def is_detail_visible(self) -> bool:
        """Check if the detail view is currently shown."""
        return self._stack.currentIndex() == 1

    # INTERNAL METHODS

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
        asset = index.data(Qt.ItemDataRole.UserRole)
        if asset:
            self.detail_requested.emit(asset.id)

    def _show_context_menu(self, pos) -> None:
        """Show context menu for the item at position."""
        # Hide preview popup when showing context menu
        self._delegate.hide_preview()
        self._current_hover_index = None

        index = self._grid.indexAt(pos)
        if not index.isValid():
            return

        asset: StandardAsset = index.data(Qt.ItemDataRole.UserRole)
        if not asset:
            return

        menu = QMenu(self)

        # Platform-specific hotkey hints
        is_mac = sys.platform == "darwin"
        cmd_hint = "⌘ Click" if is_mac else "Ctrl+Click"
        alt_hint = "⌥ Click" if is_mac else "Alt+Click"

        # Get the node label for this asset type (e.g., "Environment Light", "Material")
        node_label = self._get_node_label(asset.type)

        # Status-dependent actions
        if asset.status == AssetStatus.CLOUD:
            if self._download_enabled:
                download_action = menu.addAction("Download")
                download_action.triggered.connect(
                    lambda: self.download_requested.emit(asset.id)
                )

            import_action = menu.addAction("Import (will download first)")
            import_action.triggered.connect(
                lambda: self.import_requested.emit(asset.id)
            )

        elif asset.status == AssetStatus.LOCAL:
            # New <asset> action with hotkey hint
            new_action = menu.addAction(f"New {node_label}\t{cmd_hint}")
            new_action.triggered.connect(
                lambda: self.new_asset_requested.emit(asset.id)
            )

            # Replace <asset> action (only if host supports it)
            if self._replace_enabled:
                replace_action = menu.addAction(
                    f"Replace {node_label}\t{alt_hint}")
                replace_action.triggered.connect(
                    lambda: self.replace_asset_requested.emit(asset.id)
                )

            if self._remove_enabled:
                menu.addSeparator()
                remove_action = menu.addAction("Remove")
                remove_action.triggered.connect(
                    lambda: self.remove_requested.emit(asset.id)
                )

        elif asset.status == AssetStatus.DOWNLOADING:
            downloading_action = menu.addAction("Downloading...")
            downloading_action.setEnabled(False)

        menu.addSeparator()
        details_action = menu.addAction("View Details")
        details_action.triggered.connect(
            lambda: self.detail_requested.emit(asset.id)
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

        asset: StandardAsset = index.data(Qt.ItemDataRole.UserRole)
        if not asset:
            return False

        # Only handle local assets (can't create/replace with cloud assets directly)
        if asset.status != AssetStatus.LOCAL:
            return False

        # Qt swaps Ctrl/Meta on macOS by default, so ControlModifier maps to:
        # - macOS: Command key (⌘)
        # - Windows/Linux: Ctrl key
        # This gives us consistent cross-platform behavior.

        # Cmd/Ctrl+Click: New asset
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._delegate.hide_preview()
            self.new_asset_requested.emit(asset.id)
            return True

        # Opt/Alt+Click: Replace asset (only if enabled)
        if modifiers & Qt.KeyboardModifier.AltModifier and self._replace_enabled:
            self._delegate.hide_preview()
            self.replace_asset_requested.emit(asset.id)
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
