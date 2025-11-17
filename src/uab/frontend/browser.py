from typing import List, Optional
from PySide6.QtCore import Qt, QSize, QPoint, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QSizePolicy,
    QLabel,
    QScrollArea,
    QVBoxLayout,
)
from PySide6.QtGui import QWheelEvent, QShowEvent
from PySide6.QtCore import QEvent

from uab.frontend.thumbnail import Thumbnail


class Browser(QWidget):
    """
    Styled Browser widget for displaying a grid of Thumbnail widgets.

    Features:
      - Dynamic resizing & reflow.
      - Ctrl + wheel = zoom centered on the mouse cursor.
      - No scrolling occurs while Ctrl is held.
      - Clean updates when thumbnails are added / removed.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setStyleSheet("""
            Browser {
                background-color: #1e1e1e;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1e1e1e;
            }
        """)

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
            }
        """)

        self.grid = QGridLayout(self.grid_container)
        self.grid.setSpacing(0)
        self.grid.setContentsMargins(20, 20, 20, 20)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop |
                               Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.grid_container)
        main_layout.addWidget(self.scroll_area)

        # Install event filter on viewport to intercept wheel events
        self.scroll_area.viewport().installEventFilter(self)

        self._thumbnails: List[Thumbnail] = []
        self._cell_min_width = 180            # base cell size
        self._last_cols = 0                   # cache column count
        self._scale_factor = 1.0              # zoom level (1.0 = default)
        self._has_shown = False               # track if widget has been shown

    # Public API

    def refresh_thumbnails(self, thumbnails: List[Thumbnail]) -> None:
        """Rebuild grid when thumbnails change."""
        self._thumbnails = list[Thumbnail](thumbnails or [])
        self._draw_thumbnails()

    # Grid management

    def _clear_grid(self) -> None:
        """Remove all items from layout cleanly."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _draw_thumbnails(self) -> None:
        """Create or refresh visible thumbnails."""
        self._clear_grid()

        if not self._thumbnails:
            self._show_empty_message()
            return

        for p in self._thumbnails:
            p.setParent(self.grid_container)

        self._reflow_grid()

    def _reflow_grid(self) -> None:
        """Re‑arrange thumbnails according to scale and container width."""
        for i in reversed(range(self.grid.count())):
            self.grid.takeAt(i)

        cols = self._compute_column_count()
        self._last_cols = cols
        size = int(self._cell_min_width * self._scale_factor)
        row, col = 0, 0

        for p in self._thumbnails:
            p.setFixedSize(QSize(size, size))
            p.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.grid.addWidget(p, row, col, Qt.AlignmentFlag.AlignTop)
            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Stretch to fill last row evenly
        for i in range(cols):
            self.grid.setColumnStretch(i, 1)

    def _compute_column_count(self) -> int:
        """Determine how many cells fit per row."""
        viewport = self.scroll_area.viewport()
        available = viewport.width()

        # If viewport hasn't been laid out yet, return a reasonable default
        # This will be corrected when showEvent or resizeEvent fires
        if available <= 0:
            # Default to 1200px
            available = 1200

        spacing = self.grid.spacing()
        margins = self.grid.contentsMargins()
        available -= margins.left() + margins.right()
        scaled_width = int(self._cell_min_width * self._scale_factor)
        return max(1, available // (scaled_width + spacing))

    def _show_empty_message(self) -> None:
        """Display a 'no assets' placeholder."""
        empty_container = QWidget()
        layout = QVBoxLayout(empty_container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("📁")
        icon.setStyleSheet("font-size: 64pt; color: #666;")
        layout.addWidget(icon)

        # BUG: if an asset is added to a fresh installation, this should be removed.
        text = QLabel("No assets to display")
        text.setStyleSheet(
            "color: #808080; font-size: 16pt; font-weight: 500;")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)

        self.grid.addWidget(empty_container, 0, 0, 1, -1)

    # Event Handlers

    def eventFilter(self, obj, event: QEvent) -> bool:
        """
        Filter events from the scroll area viewport.
        Intercept wheel events when Ctrl is held to prevent scrolling.
        """
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            # event is already a QWheelEvent when type is Wheel
            wheel_event: QWheelEvent = event  # type: ignore
            if wheel_event.modifiers() & Qt.ControlModifier:
                # Handle zoom instead of scrolling
                self._handle_zoom(wheel_event)
                return True  # Event handled, don't propagate
        return super().eventFilter(obj, event)

    def showEvent(self, event: QShowEvent):
        """Trigger reflow when widget is first shown to fix initial layout."""
        super().showEvent(event)
        if not self._has_shown and self._thumbnails:
            # Defer reflow to ensure layout is complete
            QTimer.singleShot(0, self._reflow_grid)
            self._has_shown = True

    def resizeEvent(self, event):
        """Re‑layout on resize if column count changes."""
        super().resizeEvent(event)
        cols = self._compute_column_count()
        if cols != self._last_cols:
            self._reflow_grid()

    def _handle_zoom(self, event: QWheelEvent):
        """
        Handle zoom operation when Ctrl+Wheel is used.
        This is called from eventFilter to prevent scroll area from scrolling.
        """
        # Get mouse position within viewport
        viewport = self.scroll_area.viewport()
        mouse_pos = viewport.mapFromGlobal(
            event.globalPosition().toPoint())

        # Scroll positions before zoom
        h_scroll = self.scroll_area.horizontalScrollBar()
        v_scroll = self.scroll_area.verticalScrollBar()

        # Position in content coordinates before zoom
        pre_x = h_scroll.value() + mouse_pos.x()
        pre_y = v_scroll.value() + mouse_pos.y()

        # Compute new zoom
        delta = event.angleDelta().y() / 240.0
        factor_change = 1.0 + delta * 0.2
        new_scale = max(0.3, min(self._scale_factor * factor_change, 2.74))

        # Ratio between old and new scales
        scale_ratio = new_scale / self._scale_factor
        self._scale_factor = new_scale

        # Reflow previews at new size
        self._reflow_grid()

        # Compute new scroll so that point under cursor stays fixed
        h_scroll.setValue(int(pre_x * scale_ratio) - mouse_pos.x())
        v_scroll.setValue(int(pre_y * scale_ratio) - mouse_pos.y())

    def wheelEvent(self, event: QWheelEvent):
        """
        Handle wheel events that reach the Browser widget directly.
        Note: Most wheel events are intercepted by eventFilter on the viewport.
        """
        if event.modifiers() & Qt.ControlModifier:
            self._handle_zoom(event)
            event.accept()
        else:
            # Default behavior
            super().wheelEvent(event)
