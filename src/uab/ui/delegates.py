"""Item delegates for Universal Asset Browser."""

from collections import OrderedDict
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, QSize, QRect, QPoint, QModelIndex, QTimer, Signal
from PySide6.QtGui import (
    QPainter,
    QPixmap,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPainterPath,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from uab.core.models import StandardAsset, AssetStatus, AssetType

if TYPE_CHECKING:
    from uab.ui.utils import LocalImageLoader


class LargePreviewPopup(QDialog):
    """Frameless popup that shows a large scaled pixmap near the hovered thumbnail."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #000;
                border: 2px solid #4a9eff;
                border-radius: 8px;
            }
            """
        )
        self._label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._label)
        self._hover = False

    def set_pixmap(self, pixmap: QPixmap, percent_of_screen: float = 0.5) -> None:
        """Set the preview pixmap, scaled to fit screen percentage."""
        if pixmap.isNull():
            self._label.setText("No Preview")
            self._label.setStyleSheet("color: #888; font-size: 10pt;")
        else:
            screen = self.screen()
            max_size = screen.availableGeometry().size() * percent_of_screen
            scaled = pixmap.scaled(
                max_size.width(),
                max_size.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._label.setPixmap(scaled)
            self._label.setStyleSheet("")

    def enterEvent(self, event) -> None:
        """Track when mouse enters the popup."""
        self._hover = True

    def leaveEvent(self, event) -> None:
        """Hide popup when mouse leaves."""
        self._hover = False
        self.schedule_hide()

    def schedule_hide(self) -> None:
        """Hide with a small delay to allow cursor transition between widgets."""
        QTimer.singleShot(100, self._safe_hide)

    def _safe_hide(self) -> None:
        """Only hide if not being hovered."""
        if not self._hover:
            self.hide()


class LRUCache:
    """Simple LRU cache for QPixmap objects."""

    def __init__(self, maxsize: int = 100):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[QPixmap]:
        """Get item from cache, moving it to end (most recently used)."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: QPixmap) -> None:
        """Add item to cache, evicting oldest if necessary."""
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = value

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class AssetColor(Enum):
    BG_NORMAL = QColor("#242424")
    BG_HOVER = QColor("#2d2d2d")
    BG_SELECTED = QColor("#2a2a2a")
    BORDER_NORMAL = QColor("#333333")
    BORDER_HOVER = QColor("#506680")
    BORDER_SELECTED = QColor("#4a9eff")
    TEXT = QColor("#e0e0e0")
    TEXT_MUTED = QColor("#666666")
    STATUS_LOCAL = QColor("#44ff44")
    STATUS_CLOUD = QColor("#888888")
    STATUS_DOWNLOADING = QColor("#4a9eff")
    TYPE_TEXTURE = QColor("#ff9944")
    TYPE_MODEL = QColor("#44ff99")
    TYPE_HDRI = QColor("#9944ff")

    @property
    def qcolor(self) -> QColor:
        return self.value


class AssetDelegate(QStyledItemDelegate):
    """
    Custom delegate for rendering asset items in the grid view.

    Renders:
    - Thumbnail image with rounded corners
    - Asset name below thumbnail
    - Status overlay (checkmark for LOCAL, cloud for CLOUD, spinner for DOWNLOADING)
    - Type badge in corner
    - Selection/hover highlighting
    """

    COLORS = AssetColor

    # Delay before showing the large preview (milliseconds)
    HOVER_PREVIEW_DELAY_MS = 1000

    thumbnail_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cell_size = 180
        self._thumbnail_cache = LRUCache(maxsize=200)
        self._placeholder_pixmap: Optional[QPixmap] = None
        self._hovered_index: Optional[QModelIndex] = None

        # Large preview popup
        self._preview_popup: Optional[LargePreviewPopup] = None
        self._hover_timer: Optional[QTimer] = None
        self._preview_asset: Optional[StandardAsset] = None
        self._preview_parent: Optional[QWidget] = None
        self._preview_item_rect: Optional[QRect] = None

        # thumbnail loading state
        self._loading_assets: set[str] = set()
        self._loading_placeholder: Optional[QPixmap] = None
        self._image_loader: Optional["LocalImageLoader"] = None

    def set_preview_parent(self, parent: QWidget) -> None:
        """Set the parent widget for the preview popup."""
        self._preview_parent = parent

    def set_hovered_index(self, index: Optional[QModelIndex]) -> None:
        """Set the currently hovered index for hover effects."""
        self._hovered_index = index

    def on_item_hover_enter(
        self, index: QModelIndex, item_rect: QRect, global_pos: QPoint
    ) -> None:
        """
        Called when the mouse enters an item's area.

        Args:
            index: The model index of the hovered item
            item_rect: The item's rectangle in viewport coordinates
            global_pos: The global position for popup placement reference
        """
        asset: Optional[StandardAsset] = index.data(Qt.ItemDataRole.UserRole)
        if asset is None:
            return

        self._preview_asset = asset
        self._preview_item_rect = item_rect

        # Cancel any pending timer
        if self._hover_timer is not None:
            self._hover_timer.stop()

        # Start a new timer to show preview after delay
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_large_preview)
        self._hover_timer.start(self.HOVER_PREVIEW_DELAY_MS)

    def on_item_hover_leave(self) -> None:
        """Called when the mouse leaves an item's area."""
        # Stop pending timer if hover leaves before delay
        if self._hover_timer is not None:
            self._hover_timer.stop()
            self._hover_timer = None

        # Schedule popup hide
        if self._preview_popup is not None:
            self._preview_popup.schedule_hide()

        self._preview_asset = None
        self._preview_item_rect = None

    def _show_large_preview(self) -> None:
        """Show the large preview popup for the currently hovered asset."""
        if self._preview_asset is None or self._preview_parent is None:
            return

        # Load full resolution image for the preview
        pixmap = self._load_full_resolution_preview(self._preview_asset)

        if pixmap is None or pixmap.isNull():
            return

        # Create popup if needed
        if self._preview_popup is None:
            self._preview_popup = LargePreviewPopup(self._preview_parent)

        self._preview_popup.set_pixmap(pixmap)
        self._preview_popup.adjustSize()

        # Position the popup
        self._position_preview_popup()
        self._preview_popup.show()

    def _load_full_resolution_preview(self, asset: StandardAsset) -> Optional[QPixmap]:
        """Load full resolution image for the large preview popup."""
        pixmap = QPixmap()

        if asset.thumbnail_path and asset.thumbnail_path.exists():
            pixmap.load(str(asset.thumbnail_path))

        # Try local_path for the actual asset file
        if pixmap.isNull() and asset.local_path and asset.local_path.exists():
            suffix = asset.local_path.suffix.lower()
            if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                pixmap.load(str(asset.local_path))
            elif suffix in (".hdr", ".exr"):
                # Use HDR/EXR loader with higher resolution for preview
                from uab.ui.utils import load_hdri_thumbnail
                hdr_pixmap = load_hdri_thumbnail(
                    asset.local_path, max_size=1024)
                if hdr_pixmap and not hdr_pixmap.isNull():
                    pixmap = hdr_pixmap

        # Fall back to model placeholder if needed
        if pixmap.isNull() and asset.type == AssetType.MODEL:
            placeholder = self._get_model_placeholder()
            if placeholder:
                pixmap = placeholder

        return pixmap if not pixmap.isNull() else None

    def _position_preview_popup(self) -> None:
        """Position the preview popup near the hovered item."""
        if (
            self._preview_popup is None
            or self._preview_item_rect is None
            or self._preview_parent is None
        ):
            return

        popup = self._preview_popup
        popup_width = popup.width()
        popup_height = popup.height()

        # Convert item rect to global coordinates
        item_top_left = self._preview_parent.mapToGlobal(
            self._preview_item_rect.topLeft()
        )
        item_bottom_right = self._preview_parent.mapToGlobal(
            self._preview_item_rect.bottomRight()
        )

        # Get screen boundaries
        screen = popup.screen()
        screen_rect = screen.availableGeometry()

        # Default position: to the right of the item
        x = item_bottom_right.x() + 10
        y = item_top_left.y()

        # If it would overflow on the right, move to the left
        if x + popup_width > screen_rect.right():
            x = item_top_left.x() - popup_width - 10

        # Clamp vertical placement inside screen
        if y + popup_height > screen_rect.bottom():
            y = screen_rect.bottom() - popup_height - 10
        if y < screen_rect.top():
            y = screen_rect.top() + 10

        popup.move(x, y)

    def hide_preview(self) -> None:
        """Immediately hide the preview popup."""
        if self._hover_timer is not None:
            self._hover_timer.stop()
            self._hover_timer = None
        if self._preview_popup is not None:
            self._preview_popup.hide()

    def set_cell_size(self, size: int) -> None:
        """Update the cell size for zoom."""
        self._cell_size = size

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return the size hint for an item."""
        # Height includes space for text below thumbnail
        return QSize(self._cell_size + 20, self._cell_size + 40)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        """Paint an asset item."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        asset: StandardAsset = index.data(Qt.ItemDataRole.UserRole)

        # Handle empty state
        if asset is None:
            self._paint_empty_state(painter, option)
            painter.restore()
            return

        rect = option.rect
        is_selected = option.state & QStyle.StateFlag.State_Selected
        # Check both the option state and our tracked hover index
        is_hover = (option.state & QStyle.StateFlag.State_MouseOver) or (
            self._hovered_index is not None and self._hovered_index == index
        )

        # Draw background and border
        self._paint_background(painter, rect, is_selected, is_hover)

        # Calculate thumbnail rect (leaving space for text)
        thumb_margin = 8
        text_height = 30
        thumb_rect = QRect(
            rect.x() + thumb_margin,
            rect.y() + thumb_margin,
            rect.width() - (thumb_margin * 2),
            rect.height() - (thumb_margin * 2) - text_height,
        )

        # Draw thumbnail
        self._paint_thumbnail(painter, thumb_rect, asset)

        # Draw status overlay
        self._paint_status_overlay(painter, thumb_rect, asset.status)

        # Draw type badge
        self._paint_type_badge(painter, thumb_rect, asset.type)

        # Draw asset name
        text_rect = QRect(
            rect.x() + thumb_margin,
            thumb_rect.bottom() + 5,
            rect.width() - (thumb_margin * 2),
            text_height,
        )
        self._paint_name(painter, text_rect, asset.name)

        painter.restore()

    def _paint_empty_state(
        self, painter: QPainter, option: QStyleOptionViewItem
    ) -> None:
        """Paint the empty state placeholder."""
        rect = option.rect
        painter.setPen(self.COLORS.TEXT_MUTED.qcolor)

        # Draw folder icon
        font = painter.font()
        font.setPointSize(48)
        painter.setFont(font)
        icon_rect = QRect(rect.x(), rect.y(), rect.width(), rect.height() - 40)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "📁")

        # Draw text
        font.setPointSize(12)
        painter.setFont(font)
        text_rect = QRect(
            rect.x(), rect.y() + rect.height() - 60, rect.width(), 40
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter,
                         "No assets to display")

    def _paint_background(
        self, painter: QPainter, rect: QRect, is_selected: bool, is_hover: bool
    ) -> None:
        """Paint the item background with rounded corners."""
        # Determine colors
        if is_selected:
            bg_color = self.COLORS.BG_SELECTED.qcolor
            border_color = self.COLORS.BORDER_SELECTED.qcolor
        elif is_hover:
            bg_color = self.COLORS.BG_HOVER.qcolor
            border_color = self.COLORS.BORDER_HOVER.qcolor
        else:
            bg_color = self.COLORS.BG_NORMAL.qcolor
            border_color = self.COLORS.BORDER_NORMAL.qcolor

        # Draw rounded rectangle
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(2, 2, -2, -2), 10, 10)

        painter.fillPath(path, QBrush(bg_color))
        painter.setPen(QPen(border_color, 2))
        painter.drawPath(path)

    def _paint_thumbnail(
        self, painter: QPainter, rect: QRect, asset: StandardAsset
    ) -> None:
        """Paint the thumbnail image."""
        pixmap = self._get_thumbnail(asset)
        if (pixmap is None or pixmap.isNull()) and asset.type == AssetType.MODEL:
            pixmap = self._get_model_placeholder()

        if pixmap and not pixmap.isNull():
            # Scale to fit while preserving aspect ratio
            scaled = pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Center in rect
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2

            # Draw with rounded corners
            path = QPainterPath()
            thumb_rect = QRect(x, y, scaled.width(), scaled.height())
            path.addRoundedRect(thumb_rect, 6, 6)
            painter.setClipPath(path)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)
        else:
            # Draw placeholder
            self._paint_placeholder(painter, rect)

    def _paint_placeholder(self, painter: QPainter, rect: QRect) -> None:
        """Paint a placeholder when no thumbnail is available."""
        # Draw inner background
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.fillPath(path, QBrush(QColor("#1a1a1a")))

        # Draw placeholder text
        painter.setPen(self.COLORS.TEXT_MUTED.qcolor)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No Preview")

    def _get_model_placeholder(self) -> Optional[QPixmap]:
        """Load and cache the model placeholder pixmap."""
        if self._placeholder_pixmap and not self._placeholder_pixmap.isNull():
            return self._placeholder_pixmap

        placeholder_path = (
            Path(__file__).resolve().parents[3]
            / "assets"
            / "model-placeholder.png"
        )
        pixmap = QPixmap()
        if placeholder_path.exists():
            pixmap.load(str(placeholder_path))

        if not pixmap.isNull():
            self._placeholder_pixmap = pixmap
            return pixmap

        return None

    def _paint_status_overlay(
        self, painter: QPainter, rect: QRect, status: AssetStatus
    ) -> None:
        """Paint the status overlay icon."""
        # Position in top-left corner
        icon_size = 20
        icon_rect = QRect(rect.x() + 5, rect.y() + 5, icon_size, icon_size)

        # Draw background circle
        if status == AssetStatus.LOCAL:
            color = self.COLORS.STATUS_LOCAL.qcolor
            icon = "✓"
        elif status == AssetStatus.CLOUD:
            color = self.COLORS.STATUS_CLOUD.qcolor
            icon = "☁"
        else:  # DOWNLOADING
            color = self.COLORS.STATUS_DOWNLOADING.qcolor
            icon = "↓"

        # Draw circle background
        painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(icon_rect)

        # Draw icon
        painter.setPen(color)
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, icon)

    def _paint_type_badge(
        self, painter: QPainter, rect: QRect, asset_type: AssetType
    ) -> None:
        """Paint the type badge in the bottom-right corner."""
        # Position in bottom-right corner
        badge_width = 40
        badge_height = 18
        badge_rect = QRect(
            rect.right() - badge_width - 5,
            rect.bottom() - badge_height - 5,
            badge_width,
            badge_height,
        )

        # Determine color and text
        if asset_type == AssetType.TEXTURE:
            color = self.COLORS.TYPE_TEXTURE.qcolor
            text = "TEX"
        elif asset_type == AssetType.MODEL:
            color = self.COLORS.TYPE_MODEL.qcolor
            text = "3D"
        else:  # HDRI
            color = self.COLORS.TYPE_HDRI.qcolor
            text = "HDR"

        # Draw badge background
        path = QPainterPath()
        path.addRoundedRect(badge_rect, 4, 4)
        painter.fillPath(path, QBrush(color))

        # Draw text
        painter.setPen(QColor("#000000"))
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_name(self, painter: QPainter, rect: QRect, name: str) -> None:
        """Paint the asset name."""
        painter.setPen(self.COLORS.TEXT.qcolor)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)

        # Elide text if too long
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(
            name, Qt.TextElideMode.ElideRight, rect.width())

        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter |
                         Qt.AlignmentFlag.AlignTop, elided)

    def _get_thumbnail(self, asset: StandardAsset) -> Optional[QPixmap]:
        """
        Get thumbnail pixmap from cache or load it.

        For slow-loading formats (HDR/EXR), returns a placeholder immediately
        and queues background loading.
        """
        cache_key = asset.id

        # Check cache first
        cached = self._thumbnail_cache.get(cache_key)
        if cached is not None:
            return cached

        # Try to load from thumbnail_path
        pixmap = QPixmap()
        if asset.thumbnail_path and asset.thumbnail_path.exists():
            pixmap.load(str(asset.thumbnail_path))
        elif asset.local_path:
            local_path = asset.local_path
            if local_path.exists():
                suffix = local_path.suffix.lower()
                if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                    pixmap.load(str(local_path))
                elif suffix in (".hdr", ".exr"):
                    # Slow-loading format: queue async load and return placeholder
                    if cache_key not in self._loading_assets and self._image_loader is not None:
                        self._loading_assets.add(cache_key)
                        max_size = self._cell_size - 16  # margins
                        self._image_loader.set_items(
                            [(cache_key, local_path, max_size)])
                        if not self._image_loader.isRunning():
                            self._image_loader.start()
                        return self._get_loading_placeholder()
        if not pixmap.isNull():
            self._thumbnail_cache.put(cache_key, pixmap)
            return pixmap

        return None

    def clear_cache(self) -> None:
        """Clear the thumbnail cache."""
        self._thumbnail_cache.clear()
