"""Composite tree widgets for browsing CompositeAsset structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTreeView,
)

from uab.core.models import Asset, AssetStatus, CompositeAsset, StandardAsset
from uab.core.tree_sections import (
    ResolutionSection,
    group_leaf_children_by_resolution,
)
from uab.ui.delegates import AssetStatusBadge


class TreeDataRole(IntEnum):
    """Custom item data roles for composite tree items."""

    ITEM = int(Qt.ItemDataRole.UserRole)
    ITEM_ID = ITEM + 1
    STATUS = ITEM + 2
    IS_COMPOSITE = ITEM + 3
    ROLE_LABEL = ITEM + 4
    IS_SECTION = ITEM + 5


@dataclass
class _TreeNode:
    item: Any | None
    parent: _TreeNode | None = None
    children: list[_TreeNode] = field(default_factory=list)

    def child(self, row: int) -> _TreeNode | None:
        if 0 <= row < len(self.children):
            return self.children[row]
        return None

    def row(self) -> int:
        if not self.parent:
            return 0
        try:
            return self.parent.children.index(self)
        except ValueError:
            return 0


def _role_label_from_metadata(item: Any) -> str:
    meta = getattr(item, "metadata", None)
    if not isinstance(meta, dict):
        return ""

    # Common cases: texture map role / map type + resolution
    map_type = meta.get("map_type") or meta.get("role")
    resolution = meta.get("resolution")
    fmt = meta.get("format")

    parts: list[str] = []
    if isinstance(map_type, str) and map_type:
        parts.append(map_type)
    if isinstance(fmt, str) and fmt and fmt not in parts:
        parts.append(fmt)
    # dont repeat resolution
    if isinstance(resolution, str) and resolution and resolution not in parts:
        parts.append(resolution)

    return " · ".join(parts)


def _coerce_asset_status(value: object) -> AssetStatus:
    """
    Normalize a status value to `AssetStatus`.

    Note: Qt will coerce `AssetStatus` (a `str`-backed Enum) into a plain `str`
    when it crosses the model/index boundary, so delegates must be resilient.
    """
    if isinstance(value, AssetStatus):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return AssetStatus.CLOUD
        # Common case: "local" / "cloud" / "downloading"
        try:
            return AssetStatus(raw)
        except ValueError:
            pass
        try:
            return AssetStatus(raw.lower())
        except ValueError:
            return AssetStatus.CLOUD
    return AssetStatus.CLOUD


class CompositeTreeModel(QAbstractItemModel):
    """A tree model that represents a CompositeAsset and its descendants."""

    def __init__(self, root: CompositeAsset | None = None, parent=None) -> None:
        super().__init__(parent)
        self._root_node = _TreeNode(item=None, parent=None)
        self._node_by_id: dict[str, _TreeNode] = {}
        self._root_composite: CompositeAsset | None = None
        if root is not None:
            self.set_root(root)

    @property
    def root_composite(self) -> CompositeAsset | None:
        return self._root_composite

    def set_root(self, composite: CompositeAsset) -> None:
        self.beginResetModel()
        try:
            self._root_composite = composite
            self._root_node.children.clear()
            self._node_by_id.clear()
            grouped_children = group_leaf_children_by_resolution(composite.children)
            self._root_node.children = [
                self._build_node(child, parent=self._root_node)
                for child in grouped_children
            ]
        finally:
            self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        try:
            self._root_composite = None
            self._root_node.children.clear()
            self._node_by_id.clear()
        finally:
            self.endResetModel()

    def _build_node(self, item: Any, parent: _TreeNode) -> _TreeNode:
        node = _TreeNode(item=item, parent=parent)
        item_id = getattr(item, "id", None)
        if isinstance(item_id, str):
            self._node_by_id[item_id] = node

        if isinstance(item, CompositeAsset):
            grouped_children = group_leaf_children_by_resolution(item.children)
            node.children = [
                self._build_node(child, parent=node) for child in grouped_children
            ]
        elif isinstance(item, ResolutionSection):
            node.children = [
                self._build_node(child, parent=node) for child in item.children
            ]
        else:
            node.children = []
        return node

    # Qt model overrides

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        node = self._node_from_index(parent)
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 1

    def index(  # noqa: N802
        self, row: int, column: int, parent: QModelIndex = QModelIndex()
    ) -> QModelIndex:
        if column != 0 or row < 0:
            return QModelIndex()

        parent_node = self._node_from_index(parent)
        child = parent_node.child(row)
        if child is None:
            return QModelIndex()
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802
        if not index.isValid():
            return QModelIndex()

        node = self._node_from_index(index)
        parent_node = node.parent
        if parent_node is None or parent_node is self._root_node:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        node = self._node_from_index(parent)
        if node.children:
            return True

        if node is self._root_node:
            return False
        item = node.item
        if isinstance(item, CompositeAsset):
            # Show an expander for composites even when children are lazily loaded.
            return True
        return False

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:  # noqa: N802, ANN401
        if not index.isValid():
            return None

        node = self._node_from_index(index)
        item = node.item
        if item is None:
            return None

        if role == int(Qt.ItemDataRole.DisplayRole):
            return getattr(item, "name", "")
        if role == int(TreeDataRole.ITEM):
            return item
        if role == int(TreeDataRole.ITEM_ID):
            if isinstance(item, ResolutionSection):
                return ""
            return getattr(item, "id", "")
        if role == int(TreeDataRole.STATUS):
            if isinstance(item, ResolutionSection):
                return None
            return getattr(item, "display_status", AssetStatus.CLOUD)
        if role == int(TreeDataRole.IS_COMPOSITE):
            return isinstance(item, CompositeAsset)
        if role == int(TreeDataRole.ROLE_LABEL):
            if isinstance(item, ResolutionSection):
                return ""
            return _role_label_from_metadata(item)
        if role == int(TreeDataRole.IS_SECTION):
            return isinstance(item, ResolutionSection)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        node = self._node_from_index(index)
        if isinstance(node.item, ResolutionSection):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # Helpers

    def _node_from_index(self, index: QModelIndex) -> _TreeNode:
        if index.isValid():
            ptr = index.internalPointer()
            if isinstance(ptr, _TreeNode):
                return ptr
        return self._root_node

    def update_item_status(self, item_id: str, status: AssetStatus) -> None:
        """
        Update a leaf item's status and refresh affected rows.

        This is intended for real-time UI updates during download.
        """
        node = self._node_by_id.get(item_id)
        if node is None or node.item is None:
            return

        item = node.item
        if isinstance(item, (Asset, StandardAsset)):
            item.status = status  # type: ignore[assignment]

        # emit dataChanged for this node and its ancestors (composite statuses are derived)
        to_update: list[_TreeNode] = []
        cur: _TreeNode | None = node
        while cur is not None and cur is not self._root_node:
            to_update.append(cur)
            cur = cur.parent

        for n in to_update:
            idx = self.createIndex(n.row(), 0, n)
            if idx.isValid():
                self.dataChanged.emit(idx, idx, [])


class CompositeTreeView(QTreeView):
    """A tree view configured for CompositeTreeModel."""

    item_expanded = Signal(str)  # item_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setAnimated(True)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIndentation(18)
        self.setRootIsDecorated(True)
        self.setExpandsOnDoubleClick(True)
        self.expanded.connect(self._on_expanded)

    def _on_expanded(self, index: QModelIndex) -> None:
        item_id = index.data(int(TreeDataRole.ITEM_ID))
        if isinstance(item_id, str) and item_id:
            self.item_expanded.emit(item_id)


class TreeItemDelegate(QStyledItemDelegate):
    """Delegate for rendering composite tree items with status + download actions."""

    download_clicked = Signal(str)  # item_id

    _COLOR_TEXT = QColor("#e0e0e0")
    _COLOR_MUTED = QColor("#7a7a7a")
    _COLOR_SELECTED = QColor("#2a2a2a")
    _COLOR_HOVER = QColor("#2d2d2d")
    _COLOR_BORDER = QColor("#333333")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._download_enabled = True

    def set_download_enabled(self, enabled: bool) -> None:
        """Enable/disable per-leaf download actions in the tree."""
        self._download_enabled = enabled
        view = self.parent()
        if isinstance(view, QTreeView):
            view.viewport().update()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # Background
        if is_selected:
            painter.fillRect(rect, self._COLOR_SELECTED)
        elif is_hover:
            painter.fillRect(rect, self._COLOR_HOVER)

        # Border
        painter.setPen(QPen(self._COLOR_BORDER, 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        item = index.data(int(TreeDataRole.ITEM))
        if item is None:
            painter.restore()
            return

        is_section = bool(index.data(int(TreeDataRole.IS_SECTION)))
        if is_section:
            section_name = getattr(item, "name", "")
            section_font = QFont(painter.font())
            section_font.setPointSize(9)
            section_font.setBold(True)
            painter.setFont(section_font)
            painter.setPen(self._COLOR_MUTED)
            painter.drawText(
                rect.x() + 10,
                rect.y(),
                max(0, rect.width() - 16),
                rect.height(),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                str(section_name),
            )
            painter.restore()
            return

        name = getattr(item, "name", "")
        status = _coerce_asset_status(index.data(int(TreeDataRole.STATUS)))

        is_composite = bool(index.data(int(TreeDataRole.IS_COMPOSITE)))
        is_mixed = bool(getattr(item, "is_mixed", False)
                        ) if is_composite else False

        role_label = index.data(int(TreeDataRole.ROLE_LABEL))
        role_label = role_label if isinstance(role_label, str) else ""

        # Layout
        margin_x = 6
        icon_size = 16
        button_size = 18

        x = rect.x() + margin_x
        y_mid = rect.y() + rect.height() // 2

        status_rect = (x, y_mid - icon_size // 2, icon_size, icon_size)
        x += icon_size + 8

        # Download button area (right)
        show_download = (
            self._download_enabled
            and not is_composite
            and status == AssetStatus.CLOUD
            and isinstance(item, (Asset, StandardAsset))
        )
        download_rect = None
        if show_download:
            download_rect = (
                rect.right() - margin_x - button_size,
                y_mid - button_size // 2,
                button_size,
                button_size,
            )

        right_limit = rect.right() - margin_x
        if download_rect is not None:
            right_limit = download_rect[0] - 8

        # Status icon
        badge = AssetStatusBadge.from_status(status, is_mixed=is_mixed)
        status_icon = badge.icon
        status_color = badge.qcolor

        painter.setPen(status_color)
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            status_rect[0],
            status_rect[1],
            status_rect[2],
            status_rect[3],
            int(Qt.AlignmentFlag.AlignCenter),
            status_icon,
        )

        # Text
        painter.setPen(self._COLOR_TEXT)
        name_font = QFont(painter.font())
        name_font.setPointSize(10)
        name_font.setBold(False)
        painter.setFont(name_font)

        metrics = QFontMetrics(name_font)
        name_right_limit = right_limit

        elided_role = ""
        label_w = 0
        role_font = None
        if role_label:
            role_font = QFont(painter.font())
            role_font.setPointSize(9)
            role_font.setItalic(False)
            label_max_w = min(200, max(0, right_limit - x))
            label_metrics = QFontMetrics(role_font)
            elided_role = label_metrics.elidedText(
                role_label, Qt.TextElideMode.ElideLeft, label_max_w
            )
            label_w = min(
                label_max_w, label_metrics.horizontalAdvance(elided_role))
            gap = 10
            name_right_limit = max(x, right_limit - label_w - gap)

        name_rect = (x, rect.y(), max(0, name_right_limit - x), rect.height())
        elided_name = metrics.elidedText(
            str(name), Qt.TextElideMode.ElideRight, name_rect[2]
        )
        painter.drawText(
            name_rect[0],
            name_rect[1],
            name_rect[2],
            name_rect[3],
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided_name,
        )

        if role_label:
            assert role_font is not None
            painter.setFont(role_font)
            painter.setPen(self._COLOR_MUTED)
            painter.drawText(
                x,
                rect.y(),
                max(0, right_limit - x),
                rect.height(),
                int(Qt.AlignmentFlag.AlignVCenter |
                    Qt.AlignmentFlag.AlignRight),
                elided_role,
            )

        # Download button
        if download_rect is not None:
            painter.setPen(QPen(QColor("#4a9eff"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                download_rect[0], download_rect[1], download_rect[2], download_rect[3], 4, 4
            )
            painter.setPen(QColor("#4a9eff"))
            painter.setFont(font)
            painter.drawText(
                download_rect[0],
                download_rect[1],
                download_rect[2],
                download_rect[3],
                int(Qt.AlignmentFlag.AlignCenter),
                "↓",
            )

        painter.restore()

    def editorEvent(  # noqa: N802
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().editorEvent(event, model, option, index)

        mouse: QMouseEvent = event  # type: ignore[assignment]
        item = index.data(int(TreeDataRole.ITEM))
        if item is None:
            return False

        is_composite = bool(index.data(int(TreeDataRole.IS_COMPOSITE)))
        status = index.data(int(TreeDataRole.STATUS))
        status = _coerce_asset_status(status)

        show_download = (
            self._download_enabled
            and not is_composite
            and status == AssetStatus.CLOUD
            and isinstance(item, (Asset, StandardAsset))
        )
        if not show_download:
            return False

        rect = option.rect
        margin_x = 6
        button_size = 18
        y_mid = rect.y() + rect.height() // 2
        download_rect = (
            rect.right() - margin_x - button_size,
            y_mid - button_size // 2,
            button_size,
            button_size,
        )

        if download_rect[0] <= mouse.position().x() <= download_rect[0] + download_rect[2] and download_rect[1] <= mouse.position().y() <= download_rect[1] + download_rect[3]:
            item_id = getattr(item, "id", None)
            if isinstance(item_id, str) and item_id:
                self.download_clicked.emit(item_id)
                return True

        return False
