"""Settings tab UI for user import preferences."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from uab.core.preferences import (
    DEFAULT_HDRI_FILE_TYPE,
    DEFAULT_HDRI_RESOLUTION,
    VALID_HDRI_FILE_TYPES,
    VALID_HDRI_RESOLUTIONS,
    normalize_hdri_file_type,
    normalize_hdri_resolution,
)


class SettingsTab(QWidget):
    """
    Main settings tab for quick-import preferences.

    This tab currently exposes HDRI quick import defaults:
    - preferred resolution/LOD
    - preferred file type
    """

    hdri_quick_import_changed = Signal(str, str)  # resolution, file_type

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        description = QLabel(
            "Set HDRI defaults for quick import (Cmd/Ctrl + click). "
            "Use regular Import when you need per-import overrides."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self._resolution_combo = QComboBox()
        self._resolution_combo.addItems(list(VALID_HDRI_RESOLUTIONS))
        form.addRow("HDRI LOD / Resolution", self._resolution_combo)

        self._file_type_combo = QComboBox()
        self._file_type_combo.addItems(list(VALID_HDRI_FILE_TYPES))
        form.addRow("HDRI File Type", self._file_type_combo)

        layout.addLayout(form)
        layout.addStretch(1)

        self._resolution_combo.currentTextChanged.connect(
            self._on_resolution_changed
        )
        self._file_type_combo.currentTextChanged.connect(self._on_file_type_changed)

        self.set_hdri_quick_import_preferences(
            resolution=DEFAULT_HDRI_RESOLUTION,
            file_type=DEFAULT_HDRI_FILE_TYPE,
        )

    def set_hdri_quick_import_preferences(
        self,
        *,
        resolution: str,
        file_type: str,
    ) -> None:
        """Set UI values for HDRI quick import preferences."""
        normalized_resolution = normalize_hdri_resolution(resolution)
        normalized_file_type = normalize_hdri_file_type(file_type)

        self._is_updating = True
        self._resolution_combo.setCurrentText(normalized_resolution)
        self._file_type_combo.setCurrentText(normalized_file_type)
        self._is_updating = False

    def get_hdri_quick_import_preferences(self) -> tuple[str, str]:
        """Return normalized HDRI quick-import values from the UI."""
        return (
            normalize_hdri_resolution(self._resolution_combo.currentText()),
            normalize_hdri_file_type(self._file_type_combo.currentText()),
        )

    def _on_resolution_changed(self, _value: str) -> None:
        if self._is_updating:
            return
        resolution, file_type = self.get_hdri_quick_import_preferences()
        self.hdri_quick_import_changed.emit(resolution, file_type)

    def _on_file_type_changed(self, _value: str) -> None:
        if self._is_updating:
            return
        resolution, file_type = self.get_hdri_quick_import_preferences()
        self.hdri_quick_import_changed.emit(resolution, file_type)
