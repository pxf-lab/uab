"""Main window for Universal Asset Browser (standalone mode).

This is a thin QMainWindow shell that hosts the MainWidget for standalone use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QWidget

from uab.ui.main_widget import MainWidget

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration
    from uab.presenters.main_presenter import MainPresenter


class MainWindow(QMainWindow):
    """
    Standalone application window that hosts the MainWidget.

    This is a thin wrapper used for the standalone desktop application.
    For embedded contexts (Houdini Python Panel), use MainWidget directly.

    Signals:
        new_tab_requested: Forwarded from MainWidget
        tab_closed: Forwarded from MainWidget
    """

    new_tab_requested = Signal(str)  # plugin_id
    tab_closed = Signal(int)  # tab index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Universal Asset Browser")
        self.resize(1050, 700)

        # Create and embed the main widget
        self._main_widget = MainWidget()
        self.setCentralWidget(self._main_widget)

        # Forward signals from main widget
        self._main_widget.new_tab_requested.connect(self.new_tab_requested)
        self._main_widget.tab_closed.connect(self.tab_closed)

    @property
    def main_widget(self) -> MainWidget:
        """Access the embedded MainWidget."""
        return self._main_widget

    def initialize(
        self, host_integration: HostIntegration | None = None
    ) -> MainPresenter:
        """
        Initialize the presenter and wire up the application.

        Delegates to MainWidget.initialize(). See MainWidget.initialize()
        for full documentation.

        Args:
            host_integration: The host integration to use. If None, a
                StandaloneIntegration will be created.

        Returns:
            The created MainPresenter instance.
        """
        return self._main_widget.initialize(host_integration)

    @property
    def presenter(self) -> MainPresenter | None:
        """The MainPresenter instance, or None if not yet initialized."""
        return self._main_widget.presenter

    @property
    def is_initialized(self) -> bool:
        """Return True if initialize() has been called."""
        return self._main_widget.is_initialized
