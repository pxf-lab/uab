from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QScrollArea,
    QFrame, QSizePolicy
)

from uab.core import utils


class Detail(QWidget):
    """
    Detail widget for full asset details and metadata editing.

    Displays:
    - Preview image (read-only)
    - Name (editable)
    - File path (editable)
    - Description (editable)
    - Tags (editable)
    """

    back_clicked = Signal()
    save_clicked = Signal(dict)  # Emits the updated asset data
    delete_clicked = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.current_asset: Optional[dict] = None
        self.is_edit_mode: bool = False

        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)

        self.btn_back = QPushButton("← Back")
        self.btn_back.setToolTip("Back to asset list")
        self.btn_back.setMaximumWidth(100)
        self.btn_back.clicked.connect(self._on_back_clicked)

        # Preview Image
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setScaledContents(False)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_label.setStyleSheet(
            "border: 1px solid #333; background-color: #0a0a0a; border-radius: 4px;")
        left_layout.addWidget(self.preview_label, 1)

        main_layout.addWidget(left_panel, 7)

        right_panel = QWidget()
        right_panel.setMinimumWidth(320)
        right_panel.setMaximumWidth(450)

        right_main_layout = QVBoxLayout(right_panel)
        right_main_layout.setContentsMargins(
            20, 20, 20, 20)
        right_main_layout.setSpacing(0)

        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setToolTip("Edit asset metadata")
        self.btn_edit.setMaximumWidth(80)
        self.btn_edit.clicked.connect(self._on_edit_clicked)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setToolTip(
            "Remove asset from library (does not delete the file on your machine)")
        self.btn_delete.setMaximumWidth(80)
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Save changes to asset metadata")
        self.btn_save.setMaximumWidth(80)
        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_save.setVisible(False)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setToolTip("Cancel changes and return to asset list")
        self.btn_cancel.setMaximumWidth(80)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        self.btn_cancel.setVisible(False)

        button_layout.addWidget(self.btn_edit)
        button_layout.addWidget(self.btn_delete)
        button_layout.addWidget(self.btn_save)
        button_layout.addWidget(self.btn_cancel)
        button_layout.addStretch()

        right_main_layout.addWidget(button_container)

        # Scroll area for metadata fields
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # Content widget for metadata fields
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20)

        # Name field
        name_layout = QVBoxLayout()
        name_layout.setSpacing(5)
        name_label = QLabel("Name")
        name_label.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #999;")
        self.name_display = QLabel()
        self.name_display.setWordWrap(True)
        self.name_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.name_display.setStyleSheet(
            "font-size: 13pt; color: #e0e0e0; padding: 5px;")

        self.name_edit = QLineEdit()
        self.name_edit.setVisible(False)
        self.name_edit.setStyleSheet("padding: 5px; font-size: 12pt;")

        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_display)
        name_layout.addWidget(self.name_edit)
        content_layout.addLayout(name_layout)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #333;")
        content_layout.addWidget(sep1)

        # File Path field
        path_layout = QVBoxLayout()
        path_layout.setSpacing(5)
        path_label = QLabel("File Path")
        path_label.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #999;")
        self.path_display = QLabel()
        self.path_display.setWordWrap(True)
        self.path_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_display.setStyleSheet(
            "color: #888; padding: 5px; font-size: 10pt;")

        self.path_edit = QLineEdit()
        self.path_edit.setVisible(False)
        self.path_edit.setStyleSheet("padding: 5px; font-size: 10pt;")

        path_layout.addWidget(path_label)
        path_layout.addWidget(self.path_display)
        path_layout.addWidget(self.path_edit)
        content_layout.addLayout(path_layout)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #333;")
        content_layout.addWidget(sep2)

        # Description field
        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(5)
        desc_label = QLabel("Description")
        desc_label.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #999;")
        self.desc_display = QLabel()
        self.desc_display.setWordWrap(True)
        self.desc_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc_display.setMinimumHeight(60)
        self.desc_display.setStyleSheet(
            "color: #ccc; padding: 5px; font-size: 11pt;")

        self.desc_edit = QTextEdit()
        self.desc_edit.setVisible(False)
        self.desc_edit.setMinimumHeight(100)
        self.desc_edit.setMaximumHeight(200)
        self.desc_edit.setStyleSheet("padding: 5px; font-size: 11pt;")

        desc_layout.addWidget(desc_label)
        desc_layout.addWidget(self.desc_display)
        desc_layout.addWidget(self.desc_edit)
        content_layout.addLayout(desc_layout)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #333;")
        content_layout.addWidget(sep3)

        # Tags field
        tags_layout = QVBoxLayout()
        tags_layout.setSpacing(5)
        tags_label = QLabel("Tags")
        tags_label.setStyleSheet(
            "font-weight: bold; font-size: 11pt; color: #999;")
        self.tags_display = QLabel()
        self.tags_display.setWordWrap(True)
        self.tags_display.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tags_display.setStyleSheet(
            "color: #ccc; padding: 5px; font-size: 11pt;")

        self.tags_edit = QLineEdit()
        self.tags_edit.setVisible(False)
        self.tags_edit.setPlaceholderText("Enter tags separated by commas")
        self.tags_edit.setStyleSheet("padding: 5px; font-size: 11pt;")

        tags_layout.addWidget(tags_label)
        tags_layout.addWidget(self.tags_display)
        tags_layout.addWidget(self.tags_edit)
        content_layout.addLayout(tags_layout)

        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        right_main_layout.addWidget(scroll_area, 1)

        # Back button at bottom right
        back_button_layout = QHBoxLayout()
        back_button_layout.addStretch()
        back_button_layout.addWidget(self.btn_back)
        right_main_layout.addLayout(back_button_layout)

        main_layout.addWidget(right_panel, 3)

    def draw_details(self, asset: dict) -> None:
        """
        Draw the full details view for the given asset.

        Args:
            asset: Dictionary containing asset data with keys:
                   name, directory_path, description, tags, id, preview_image_file_path
        """
        self.current_asset = asset
        self.display_metadata(asset)
        self._set_edit_mode(False)

    def display_metadata(self, asset: dict) -> None:
        """
        Display metadata for the given asset without entering edit mode.

        Args:
            asset: Dictionary containing asset data
        """
        if not asset:
            return

        # TODO: @thumbnail.py has a method that does exactly the same thing.
        pixmap = QPixmap()
        directory_path = Path(asset.get('path', ''))
        if directory_path and directory_path.exists():
            try:
                byte_image = utils.hdr_to_preview(
                    directory_path, as_bytes=True)
                pixmap.loadFromData(byte_image)
            except Exception as e:
                print(f"Error loading preview: {e}")

            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.preview_label.width() - 40,
                    self.preview_label.height() - 40,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
            else:
                self.preview_label.setText("Preview not available")
                self.preview_label.setStyleSheet(
                    "border: 1px solid #333; background-color: #0a0a0a; "
                    "border-radius: 4px; color: #666; font-size: 14pt;"
                )
        else:
            self.preview_label.setText("Preview not available")
            self.preview_label.setStyleSheet(
                "border: 1px solid #333; background-color: #0a0a0a; "
                "border-radius: 4px; color: #666; font-size: 14pt;"
            )

        # Display name
        name = asset.get('name', 'Unnamed Asset')
        self.name_display.setText(name)
        self.name_edit.setText(name)

        # Display file path
        path = asset.get('directory_path', 'No path specified')
        self.path_display.setText(path)
        self.path_edit.setText(path)

        # Display description
        description = asset.get('description') or 'No description provided'
        self.desc_display.setText(description)
        self.desc_edit.setPlainText(asset.get('description', ''))

        # Display tags
        tags = asset.get('tags', [])
        if isinstance(tags, list):
            tags_str = ', '.join(tags) if tags else 'No tags'
        else:
            tags_str = str(tags) if tags else 'No tags'
        self.tags_display.setText(tags_str)
        self.tags_edit.setText(
            ', '.join(tags) if isinstance(tags, list) else str(tags))

    def edit_metadata(self, asset: dict) -> None:
        """
        Enter edit mode for the asset metadata.

        Args:
            asset: Dictionary containing asset data
        """
        self.current_asset = asset
        self.display_metadata(asset)
        self._set_edit_mode(True)

    def save_metadata_changes(self) -> dict:
        """
        Collect the edited metadata and prepare it for saving.

        Returns:
            Dictionary with updated asset data
        """
        if not self.current_asset:
            return {}

        # Collect the edited values
        updated_asset = dict(self.current_asset)
        updated_asset['name'] = self.name_edit.text()
        updated_asset['directory_path'] = self.path_edit.text()
        updated_asset['description'] = self.desc_edit.toPlainText()

        # Parse tags
        tags_text = self.tags_edit.text()
        if tags_text:
            tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
            updated_asset['tags'] = tags
        else:
            updated_asset['tags'] = []

        return updated_asset

    def _set_edit_mode(self, edit_mode: bool) -> None:
        """
        Toggle between display and edit mode.

        Args:
            edit_mode: True to enable editing, False to disable
        """
        self.is_edit_mode = edit_mode

        # Toggle visibility of display vs edit widgets
        self.name_display.setVisible(not edit_mode)
        self.name_edit.setVisible(edit_mode)

        self.path_display.setVisible(not edit_mode)
        self.path_edit.setVisible(edit_mode)

        self.desc_display.setVisible(not edit_mode)
        self.desc_edit.setVisible(edit_mode)

        self.tags_display.setVisible(not edit_mode)
        self.tags_edit.setVisible(edit_mode)

        # Toggle button visibility
        self.btn_edit.setVisible(not edit_mode)
        self.btn_save.setVisible(edit_mode)
        self.btn_cancel.setVisible(edit_mode)

    def _on_back_clicked(self) -> None:
        """Handle back button click."""
        self.back_clicked.emit()

    def _on_delete_clicked(self) -> None:
        self.delete_clicked.emit(
            self.current_asset['id'] if self.current_asset else -1)

    def _on_edit_clicked(self) -> None:
        """Handle edit button click."""
        if self.current_asset:
            self.edit_metadata(self.current_asset)

    def _on_save_clicked(self) -> None:
        """Handle save button click."""
        updated_asset = self.save_metadata_changes()
        if updated_asset:
            # Update the display with the new values
            self.display_metadata(updated_asset)
            self._set_edit_mode(False)
            # Emit signal with updated asset
            self.save_clicked.emit(updated_asset)

    def _on_cancel_clicked(self) -> None:
        """Handle cancel button click."""
        # Restore original values
        if self.current_asset:
            self.display_metadata(self.current_asset)
        self._set_edit_mode(False)
