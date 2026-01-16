"""Browser view for Universal Asset Browser."""

from typing import Optional

from PySide6.QtCore import (
    Qt,
    Signal,
    QSize,
    QTimer,
    QEvent,
)
from PySide6.QtGui import QWheelEvent, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListView,
    QLineEdit,
    QComboBox,
    QLabel,
    QSplitter,
    QProgressBar,
    QMenu,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem

from uab.core.models import StandardAsset, AssetStatus
from uab.ui.delegates import AssetDelegate


class BrowserView(QWidget):
    """
    Main browser widget containing search, grid view, and detail panel.

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

        self._init_ui()
        self._setup_connections()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        self._toolbar = self._create_toolbar()
        main_layout.addWidget(self._toolbar)

        # Main content area with splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        # Grid view
        self._grid = self._create_grid_view()
        self._splitter.addWidget(self._grid)

        # Detail panel (initially hidden)
        self._detail_panel = self._create_detail_panel()
        self._detail_panel.setVisible(False)
        self._splitter.addWidget(self._detail_panel)

        # Set initial splitter sizes
        self._splitter.setSizes([1000, 0])

        main_layout.addWidget(self._splitter, 1)

        # Progress bar (hidden by default)
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(20)
        main_layout.addWidget(self._progress_bar)

        # Loading indicator
        self._loading_label = QLabel("Loading...")
        self._loading_label.setObjectName("loadingIndicator")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setVisible(False)

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

        layout.addWidget(self._search_bar, 1)
        layout.addWidget(filter_label)
        layout.addWidget(self._filter_combo)
        layout.addWidget(renderer_label)
        layout.addWidget(self._renderer_combo)
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
        grid.setItemDelegate(self._delegate)

        # Context menu
        grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Install event filter for Ctrl+wheel zoom
        grid.viewport().installEventFilter(self)

        return grid

    def _create_detail_panel(self) -> QWidget:
        """Create the detail panel for asset inspection."""
        # TODO: this is just a placeholder split detail panel. Review the prototype's implementation.
        panel = QWidget()
        panel.setObjectName("detailPanel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(400)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Close button at top
        close_btn = QPushButton("Close")
        close_btn.setMaximumWidth(60)
        close_btn.clicked.connect(self.hide_detail)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)

        # Preview image
        self._detail_preview = QLabel()
        self._detail_preview.setObjectName("detailPreview")
        self._detail_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_preview.setMinimumHeight(200)
        self._detail_preview.setScaledContents(False)
        self._detail_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        content_layout.addWidget(self._detail_preview)

        # Name
        self._detail_name = QLabel()
        self._detail_name.setWordWrap(True)
        self._detail_name.setProperty("class", "fieldValue")
        self._detail_name.setStyleSheet("font-size: 14pt; font-weight: bold;")
        content_layout.addWidget(self._detail_name)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        content_layout.addWidget(sep1)

        # Type
        type_label = QLabel("Type")
        type_label.setProperty("class", "fieldLabel")
        type_label.setStyleSheet("font-weight: bold; color: #999;")
        self._detail_type = QLabel()
        self._detail_type.setProperty("class", "fieldValue")
        content_layout.addWidget(type_label)
        content_layout.addWidget(self._detail_type)

        # Status
        status_label = QLabel("Status")
        status_label.setProperty("class", "fieldLabel")
        status_label.setStyleSheet("font-weight: bold; color: #999;")
        self._detail_status = QLabel()
        self._detail_status.setProperty("class", "fieldValue")
        content_layout.addWidget(status_label)
        content_layout.addWidget(self._detail_status)

        # Source
        source_label = QLabel("Source")
        source_label.setProperty("class", "fieldLabel")
        source_label.setStyleSheet("font-weight: bold; color: #999;")
        self._detail_source = QLabel()
        self._detail_source.setProperty("class", "fieldValue")
        content_layout.addWidget(source_label)
        content_layout.addWidget(self._detail_source)

        # Path (for local assets)
        path_label = QLabel("Path")
        path_label.setProperty("class", "fieldLabel")
        path_label.setStyleSheet("font-weight: bold; color: #999;")
        self._detail_path = QLabel()
        self._detail_path.setProperty("class", "fieldValueMuted")
        self._detail_path.setWordWrap(True)
        content_layout.addWidget(path_label)
        content_layout.addWidget(self._detail_path)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._detail_download_btn = QPushButton("Download")
        self._detail_download_btn.clicked.connect(self._on_detail_download)
        btn_layout.addWidget(self._detail_download_btn)

        self._detail_import_btn = QPushButton("Import")
        self._detail_import_btn.setObjectName("primaryButton")
        self._detail_import_btn.clicked.connect(self._on_detail_import)
        btn_layout.addWidget(self._detail_import_btn)

        layout.addLayout(btn_layout)

        return panel

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

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

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

    def set_remove_enabled(self, enabled: bool) -> None:
        """Enable or disable remove capability."""
        self._remove_enabled = enabled

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
        Display the detail panel for an asset.

        Args:
            asset: The asset to display details for
        """
        # TODO: this is just a placeholder. Review the prototype's implementation.
        self._current_detail_asset = asset

        # Update detail panel content
        self._detail_name.setText(asset.name)
        self._detail_type.setText(asset.type.value.upper())
        self._detail_status.setText(asset.status.value.upper())
        self._detail_source.setText(asset.source)

        if asset.local_path:
            self._detail_path.setText(str(asset.local_path))
            self._detail_path.setVisible(True)
        else:
            self._detail_path.setVisible(False)

        # Update button states
        self._detail_download_btn.setVisible(
            asset.status == AssetStatus.CLOUD and self._download_enabled
        )
        self._detail_import_btn.setEnabled(asset.status == AssetStatus.LOCAL)

        # Load preview image
        self._load_detail_preview(asset)

        # Show panel with animation
        if not self._detail_panel.isVisible():
            self._detail_panel.setVisible(True)
            self._splitter.setSizes([700, 300])

    def hide_detail(self) -> None:
        """Hide the detail panel."""
        self._detail_panel.setVisible(False)
        self._splitter.setSizes([1000, 0])
        self._current_detail_asset = None

    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------

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
        # TODO: this is just a placeholder. Review the prototype's implementation. Options need to change per-environment and asset status.
        index = self._grid.indexAt(pos)
        if not index.isValid():
            return

        asset: StandardAsset = index.data(Qt.ItemDataRole.UserRole)
        if not asset:
            return

        menu = QMenu(self)

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
            import_action = menu.addAction("Import")
            import_action.triggered.connect(
                lambda: self.import_requested.emit(asset.id)
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

    def _on_detail_download(self) -> None:
        """Handle download button click in detail panel."""
        if hasattr(self, "_current_detail_asset") and self._current_detail_asset:
            self.download_requested.emit(self._current_detail_asset.id)

    def _on_detail_import(self) -> None:
        """Handle import button click in detail panel."""
        if hasattr(self, "_current_detail_asset") and self._current_detail_asset:
            self.import_requested.emit(self._current_detail_asset.id)

    def _load_detail_preview(self, asset: StandardAsset) -> None:
        """Load the preview image for the detail panel."""
        pixmap = QPixmap()

        # Try thumbnail_path first, then thumbnail_url
        if asset.thumbnail_path and asset.thumbnail_path.exists():
            pixmap.load(str(asset.thumbnail_path))
        elif asset.local_path and asset.local_path.exists():
            # Try to load from local path for image assets
            if asset.local_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
                pixmap.load(str(asset.local_path))

        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self._detail_preview.width() - 20,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._detail_preview.setPixmap(scaled)
        else:
            self._detail_preview.setText("No preview available")
            self._detail_preview.setProperty("noPreview", True)

    def _handle_zoom(self, event: QWheelEvent) -> None:
        """Handle Ctrl+wheel zoom."""
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
        """Filter events for Ctrl+wheel zoom and hover tracking on grid viewport."""
        if obj == self._grid.viewport():
            if event.type() == QEvent.Type.Wheel:
                wheel_event: QWheelEvent = event
                if wheel_event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._handle_zoom(wheel_event)
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                # Track hover for delegate
                pos = event.pos()
                index = self._grid.indexAt(pos)
                if index.isValid():
                    self._delegate.set_hovered_index(index)
                else:
                    self._delegate.set_hovered_index(None)
                self._grid.viewport().update()
            elif event.type() == QEvent.Type.Leave:
                # Clear hover when mouse leaves
                self._delegate.set_hovered_index(None)
                self._grid.viewport().update()
        return super().eventFilter(obj, event)
