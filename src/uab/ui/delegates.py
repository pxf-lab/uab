"""Item delegates for Universal Asset Browser."""

from collections import OrderedDict
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QRect, QPoint, QModelIndex
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
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle

from uab.core.models import StandardAsset, AssetStatus, AssetType


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cell_size = 180
        self._thumbnail_cache = LRUCache(maxsize=200)
        self._placeholder_pixmap: Optional[QPixmap] = None
        self._hovered_index: Optional[QModelIndex] = None

    def set_hovered_index(self, index: Optional[QModelIndex]) -> None:
        """Set the currently hovered index for hover effects."""
        self._hovered_index = index

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
        """Get thumbnail pixmap from cache or load it."""
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
            # Try to load from local_path for image assets
            local_path = asset.local_path
            if local_path.exists():
                suffix = local_path.suffix.lower()
                if suffix in (".png", ".jpg", ".jpeg", ".bmp"):
                    pixmap.load(str(local_path))
                elif suffix in (".hdr", ".exr"):
                    # Use HDR/EXR loader utility
                    from uab.ui.utils import load_hdri_thumbnail
                    hdr_pixmap = load_hdri_thumbnail(local_path, max_size=256)
                    if hdr_pixmap and not hdr_pixmap.isNull():
                        pixmap = hdr_pixmap

        if not pixmap.isNull():
            self._thumbnail_cache.put(cache_key, pixmap)
            return pixmap

        return None

    def clear_cache(self) -> None:
        """Clear the thumbnail cache."""
        self._thumbnail_cache.clear()
