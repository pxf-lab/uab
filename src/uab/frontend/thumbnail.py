from typing import Optional, List
import os
from PySide6.QtCore import QPoint, Qt, QEvent, Signal, QTimer
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QSizePolicy,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGraphicsDropShadowEffect,
    QDialog,
    QMenu,
    QWidgetAction,
)
from uab.core import utils
from uab.core.assets import Asset


class LargePreviewPopup(QDialog):
    """Frameless popup that shows a large scaled pixmap near the hovered widget."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #000;
                border: 2px solid #4a9eff;
                border-radius: 8px;
            }
            """
        )
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.label)
        self._hover = False
        self._pending_hide = False

    def set_pixmap(self, pm: QPixmap, percent_of_screen: float = 0.5):
        # Fit to a large size (limit for screen safety)
        if pm.isNull():
            self.label.setText("No Preview")
            self.label.setStyleSheet("color:#888; font-size:10pt;")
        else:
            screen = self.screen()
            max_size = screen.availableGeometry().size() * percent_of_screen
            scaled = pm.scaled(
                max_size.width(),
                max_size.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.label.setPixmap(scaled)
            self.label.setStyleSheet("")

    def enterEvent(self, event):
        self._hover = True

    def leaveEvent(self, event):
        self._hover = False
        self.schedule_hide()

    def schedule_hide(self):
        """Hide with a small delay — lets the cursor transition between widgets."""
        QTimer.singleShot(100, self.safe_hide)

    def safe_hide(self):
        if not self._hover:
            self.hide()


class Thumbnail(QWidget):
    # Signals emit Asset objects as 'object' type to avoid QVariantMap conversion
    # issues in Houdini where PySide6 automatically converts dict signals.
    asset_clicked = Signal(object)
    asset_double_clicked = Signal(object)
    open_image_requested = Signal(object)
    reveal_in_file_system_requested = Signal(object)
    instantiate_requested = Signal(object)
    replace_texture_requested = Signal(object)
    context_menu_requested = Signal(object)

    def __init__(
        self,
        asset: Asset,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset.id
        self.asset_name = asset.name
        self.thumbnail: QPixmap = self._load_thumbnail_preview_from_file()
        self.is_selected = False
        self._hover = False
        self._large_preview = LargePreviewPopup(self)

        # core styling
        self.setStyleSheet("""
            Preview {
                background-color: #242424;
                border: 2px solid #333333;
                border-radius: 10px;
            }
        """)

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        # layout structure
        self.vlayout = QVBoxLayout(self)
        self.vlayout.setContentsMargins(4, 4, 4, 4)
        self.vlayout.setSpacing(2)

        # image container
        self.image_container = QWidget()
        self.image_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_container.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-radius: 6px;
                border: 2px solid #333333;
            }
        """)
        self.image_container.installEventFilter(self)
        self.vlayout.addWidget(self.image_container, 1)

        # shadow for selected state
        self.shadow = QGraphicsDropShadowEffect(blurRadius=20)
        self.shadow.setColor(QColor(0, 150, 255, 180))
        self.shadow.setOffset(0, 0)
        self.shadow.setEnabled(False)
        self.image_container.setGraphicsEffect(self.shadow)

        # image display
        img_layout = QVBoxLayout(self.image_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        self.label_icon = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label_icon.setScaledContents(False)
        img_layout.addWidget(self.label_icon)

        # text
        self.text_container = QWidget()
        tlay = QHBoxLayout(self.text_container)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(3)

        self.label_text = QLabel(self.asset_name)
        self.label_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_text.setWordWrap(True)
        self.label_text.setStyleSheet("""
            QLabel {
                color: #e0e0e0; font-size: 10pt;
                background: transparent;
            }
        """)

        tlay.addStretch(1)
        tlay.addWidget(self.label_text)
        tlay.addStretch(1)
        self.vlayout.addWidget(self.text_container)

        self._update_pixmap_display()

    def _load_thumbnail_preview_from_file(self) -> QPixmap:
        """Load thumbnail from asset's path or preview_image_file_path."""
        pixmap = QPixmap()
        dir_path = self.asset.path or ''

        # Normalize the directory path
        norm = os.path.normpath(str(dir_path)) if dir_path else ''

        if norm and (norm.lower().endswith('.hdr') or norm.lower().endswith('.exr')) and os.path.isfile(norm):
            try:
                # Use hdr_to_preview to generate a tone-mapped preview
                byte_image = utils.hdri_to_pixmap_format(norm, as_bytes=True)
                # Convert PIL Image to QPixmap
                pixmap.loadFromData(byte_image)
            except Exception as e:
                print(f"Error loading HDR preview for {norm}: {e}")
                pixmap = QPixmap()

        return pixmap

    # Events Handlers

    def eventFilter(self, obj, ev):
        if obj == self.image_container:
            if ev.type() == QEvent.Type.Enter:
                self._hover = True
                self._update_style()
                self._is_user_hovering_thumbnail()
            elif ev.type() == QEvent.Type.Leave:
                self._hover = False
                self._update_style()
                self._hide_large_preview_delayed()
        return super().eventFilter(obj, ev)

    def _is_user_hovering_thumbnail(self):
        if self.thumbnail.isNull():
            return

        # Cancel any previous pending timer
        try:
            self._hover_timer.stop()
        except AttributeError:
            pass

        # Wait 1s before showing preview
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_large_preview_window)
        self._hover_timer.start(1000)

    def _show_large_preview_window(self):
        self._large_preview.set_pixmap(self.thumbnail)

        popup = self._large_preview
        popup.adjustSize()

        # Compute position in global coordinates
        parent_global = self.mapToGlobal(self.image_container.pos())
        widget_rect = self.image_container.rect()
        widget_bottom_right = parent_global + widget_rect.bottomRight()
        w = popup.width()
        h = popup.height()

        # Get screen boundaries
        screen = self.screen()
        screen_rect = screen.availableGeometry()

        # Default position: to the right
        x = widget_bottom_right.x() + 10
        y = parent_global.y()

        # If it would overflow on the right, move to the left
        if x + w > screen_rect.right():
            x = parent_global.x() - w - 10

        # Clamp vertical placement inside screen
        if y + h > screen_rect.bottom():
            y = screen_rect.bottom() - h - 10
        if y < screen_rect.top():
            y = screen_rect.top() + 10

        popup.move(x, y)
        popup.show()

    def _hide_large_preview_delayed(self):
        # Stop pending timer if hover leaves before 1 s
        if hasattr(self, "_hover_timer"):
            self._hover_timer.stop()
        self._large_preview.schedule_hide()

    def mousePressEvent(self, e):
        """QT LMB pressed event handler."""
        if e.button() == Qt.MouseButton.LeftButton:
            if self.image_container.geometry().contains(e.pos()):
                modifiers = e.modifiers()
                if (
                    modifiers & Qt.KeyboardModifier.ControlModifier
                    or modifiers & Qt.KeyboardModifier.MetaModifier
                ):
                    self.instantiate_requested.emit(self.asset)
                elif modifiers & Qt.KeyboardModifier.AltModifier:
                    self.replace_texture_requested.emit(self.asset)
                else:
                    self.asset_clicked.emit(self.asset)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.image_container.geometry().contains(e.pos()):
                self.asset_double_clicked.emit(self.asset)
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        """Show context menu on right-click."""
        self.context_menu_requested.emit(
            {"object": self, "position": e.globalPos()})

    def create_context_menu_options(self, options: List[dict], position: QPoint):
        menu = QMenu(self)
        for option in options:
            action = self.make_menu_action(
                option["label"], option["shortcut"], menu)
            # Using the default parameter ensures that the callback is defined
            # at definition time, not at execution time.
            # This is necessary because the callback is a lambda function
            # that captures the option variable, and if the lambda is called
            # at execution time, the option variable will be the last value it had,
            # not the intended option, since the lambda accesses it by reference.
            # Example: without this, if the last optionin the list is "Open Image",
            # then all of the callbacks will call the open image logic.
            # `checked=False` is necessary since triggered emits a Signal with a bool,
            # which is caught by the lambda, so must be handled to avoid a `TypeError`.
            action.triggered.connect(
                lambda checked=False, opt=option: opt["callback"](self.asset))
            menu.addAction(action)
        menu.exec(position)

    def make_menu_action(self, text, shortcut, parent):
        wa = QWidgetAction(parent)

        class HoverableWidget(QWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                self.setStyleSheet("""
                    QWidget {
                        background: transparent;
                        border-radius: 2px;
                        padding: 2px;
                    }
                    QWidget:hover {
                        background: #34425C;
                        padding: 2px;
                    }
                """)

        w = HoverableWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(6, 2, 6, 2)

        label_text = QLabel(text)
        label_shortcut = QLabel(shortcut)

        f = label_shortcut.font()
        f.setItalic(True)
        label_shortcut.setFont(f)

        layout.addWidget(label_text)
        layout.addStretch()
        layout.addWidget(label_shortcut)

        wa.setDefaultWidget(w)
        return wa

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def _update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                Preview {
                    background-color: #2a2a2a;
                    border: 2px solid #4a9eff;
                    border-radius: 10px;
                }
            """)
            self.image_container.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border: 2px solid #4a9eff;
                    border-radius: 6px;
                }
            """)
            self.shadow.setEnabled(True)
        elif self._hover:
            self.setStyleSheet("""
                Preview {
                    background-color: #2d2d2d;
                    border: 2px solid #506680;
                    border-radius: 10px;
                }
            """)
            self.image_container.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border: 2px solid #506680;
                    border-radius: 6px;
                }
            """)
            self.shadow.setEnabled(False)
        else:
            self.setStyleSheet("""
                Preview {
                    background-color: #242424;
                    border: 2px solid #333333;
                    border-radius: 10px;
                }
            """)
            self.image_container.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border: 2px solid #333333;
                    border-radius: 6px;
                }
            """)
            self.shadow.setEnabled(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_pixmap_display()
        if self.height() < 80:
            self.text_container.hide()
        else:
            self.text_container.show()

    def _update_pixmap_display(self):
        if self.thumbnail.isNull():
            self.label_icon.setText("No Preview")
            self.label_icon.setStyleSheet(
                "color:#666; font-size:9pt; background:transparent;"
            )
            self.label_icon.setPixmap(QPixmap())
            return
        size = self.image_container.size()
        if size.width() < 1 or size.height() < 1:
            return
        scaled = self.thumbnail.scaled(
            size.width() - 6,
            size.height() - 6,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.label_icon.setPixmap(scaled)
