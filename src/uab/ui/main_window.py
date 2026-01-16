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
        - new_tab_requested: Forwarded from MainWidget
        - tab_closed: Forwarded from MainWidget
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

    # -------------------------------------------------------------------------
    # Initialization API (delegates to MainWidget)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Delegate API methods to MainWidget for convenience
    # -------------------------------------------------------------------------

    def populate_new_tab_menu(self, plugins: dict[str, str]) -> None:
        """Populate the New Tab submenu with available plugins."""
        self._main_widget.populate_new_tab_menu(plugins)

    def add_tab(self, widget: QWidget, title: str) -> int:
        """Add a new tab with the given widget."""
        return self._main_widget.add_tab(widget, title)

    def remove_tab(self, index: int) -> None:
        """Remove the tab at the given index."""
        self._main_widget.remove_tab(index)

    def set_status(self, message: str, timeout: int = 5000) -> None:
        """Display a message in the status bar."""
        self._main_widget.set_status(message, timeout)

    def current_tab_index(self) -> int:
        """Return the index of the currently active tab."""
        return self._main_widget.current_tab_index()

    def tab_count(self) -> int:
        """Return the number of tabs."""
        return self._main_widget.tab_count()
