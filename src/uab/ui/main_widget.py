"""Main widget for Universal Asset Browser.

This is the core UI component that can be embedded in any QWidget container,
including Houdini Python panels.

Architecture Note:
    In embedded contexts like Houdini's Python Panel, the host expects a QWidget
    to be returned from onCreateInterface(). This widget owns its MainPresenter
    via lazy initialization through the initialize() method. This ensures the
    widget's lifetime naturally manages the presenter's lifetime.

Usage:
    # Standalone
    widget = MainWidget()
    widget.initialize()  # Uses StandaloneIntegration

    # Houdini Python Panel
    widget = MainWidget()
    widget.initialize(host_integration=HoudiniIntegration())
    return widget
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QTabBar,
    QMenuBar,
    QMenu,
    QPushButton,
    QMessageBox,
)

from uab.ui.status_bar import StatusBar

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration
    from uab.presenters.main_presenter import MainPresenter


class MainWidget(QWidget):
    """
    Application shell with tab widget, menus, and status bar.

    This widget contains all the main UI functionality and can be embedded
    directly in a Houdini Python panel or hosted by MainWindow for standalone use.

    The widget owns its presenter, which is created via the initialize() method.
    This pattern ensures proper lifetime management in embedded contexts where
    only the widget reference is retained by the host.

    Signals:
        new_tab_requested: Emitted when user requests a new tab for a plugin.
        tab_closed: Emitted when user closes a tab.

    Attributes:
        presenter: The MainPresenter instance (None until initialize() is called)
    """

    new_tab_requested = Signal(str)  # plugin_id
    tab_closed = Signal(int)  # tab index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Presenter is created lazily via initialize()
        self._presenter: MainPresenter | None = None

        # Load stylesheet
        self._load_stylesheet()

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Menu bar (as a regular widget in layout)
        self._menu_bar = QMenuBar()
        self._menu_bar.setObjectName("mainMenuBar")
        layout.addWidget(self._menu_bar)
        self._setup_menus()

        # Tab widget (browser-style)
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(False)  # We use custom close buttons
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setElideMode(Qt.TextElideMode.ElideRight)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        layout.addWidget(self._tab_widget, 1)  # stretch factor 1

        # New tab button (like browser + button)
        self._new_tab_btn = QPushButton("+")
        self._new_tab_btn.setObjectName("newTabButton")
        self._new_tab_btn.setFixedSize(32, 32)
        self._new_tab_btn.setToolTip("New Tab")
        self._new_tab_btn.clicked.connect(self._on_new_tab_clicked)

        # Create a container for the corner widget to add padding
        corner_container = QWidget()
        corner_container.setFixedSize(40, 36)
        corner_container.setStyleSheet("background: transparent;")
        self._new_tab_btn.setParent(corner_container)
        self._new_tab_btn.move(4, 2)

        # Add new tab button to the right of tab bar
        self._tab_widget.setCornerWidget(corner_container, Qt.Corner.TopRightCorner)

        # Status bar
        self._status_bar = StatusBar()
        self._status_bar.setObjectName("statusBar")
        layout.addWidget(self._status_bar)

    def _load_stylesheet(self) -> None:
        """Load the application stylesheet from styles.qss."""
        style_path = Path(__file__).parent / "styles.qss"
        if style_path.exists():
            with open(style_path, "r") as f:
                self.setStyleSheet(f.read())

    def _setup_menus(self) -> None:
        """Set up the menu bar with File and Help menus."""
        # File menu
        file_menu = QMenu("&File", self)
        self._menu_bar.addMenu(file_menu)

        # New Tab submenu - populated dynamically via populate_new_tab_menu
        self._new_tab_menu = QMenu("New Tab", self)
        file_menu.addMenu(self._new_tab_menu)

        file_menu.addSeparator()

        # Close Tab action
        close_tab_action = file_menu.addAction("Close Tab")
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(self._close_current_tab)

        # Help menu
        help_menu = QMenu("&Help", self)
        self._menu_bar.addMenu(help_menu)

        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._show_about)

    def populate_new_tab_menu(self, plugins: dict[str, str]) -> None:
        """
        Populate the New Tab submenu with available plugins.

        Args:
            plugins: Dict mapping plugin_id to display_name
        """
        self._new_tab_menu.clear()
        for plugin_id, display_name in plugins.items():
            action = self._new_tab_menu.addAction(display_name)
            # Capture plugin_id in lambda closure
            action.triggered.connect(
                lambda checked=False, pid=plugin_id: self.new_tab_requested.emit(pid)
            )

    def add_tab(self, widget: QWidget, title: str) -> int:
        """
        Add a new tab with the given widget.

        Args:
            widget: The widget to add as tab content
            title: The tab title

        Returns:
            The index of the new tab
        """
        index = self._tab_widget.addTab(widget, title)
        self._tab_widget.setCurrentIndex(index)

        # Add custom close button
        close_btn = self._create_close_button(index)
        self._tab_widget.tabBar().setTabButton(
            index, QTabBar.ButtonPosition.RightSide, close_btn
        )

        return index

    def _create_close_button(self, tab_index: int) -> QPushButton:
        """Create a custom close button for a tab."""
        btn = QPushButton("×")
        btn.setObjectName("tabCloseButton")
        btn.setFixedSize(20, 20)
        btn.setToolTip("Close Tab")
        # Find the actual tab index when clicked (handles reordering)
        btn.clicked.connect(lambda: self._close_tab_for_button(btn))
        return btn

    def _close_tab_for_button(self, button: QPushButton) -> None:
        """Find and close the tab associated with this close button."""
        tab_bar = self._tab_widget.tabBar()
        for i in range(tab_bar.count()):
            if tab_bar.tabButton(i, QTabBar.ButtonPosition.RightSide) == button:
                self._on_tab_close_requested(i)
                break

    def remove_tab(self, index: int) -> None:
        """
        Remove the tab at the given index.

        Args:
            index: The tab index to remove
        """
        self._tab_widget.removeTab(index)

    def set_status(self, message: str, timeout: int = 5000) -> None:
        """
        Display a message in the status bar.

        Args:
            message: The message to display
            timeout: Time in milliseconds before message clears (0 = permanent)
        """
        self._status_bar.show_message(message, timeout=timeout)

    def current_tab_index(self) -> int:
        """Return the index of the currently active tab."""
        return self._tab_widget.currentIndex()

    def tab_count(self) -> int:
        """Return the number of tabs."""
        return self._tab_widget.count()

    def _on_tab_close_requested(self, index: int) -> None:
        """Handle tab close button click."""
        self.tab_closed.emit(index)

    def _close_current_tab(self) -> None:
        """Close the currently active tab."""
        index = self._tab_widget.currentIndex()
        if index >= 0:
            self.tab_closed.emit(index)

    def _on_new_tab_clicked(self) -> None:
        """Handle new tab button click - shows menu if multiple plugins available."""
        if self._new_tab_menu.actions():
            # Position menu below the button
            pos = self._new_tab_btn.mapToGlobal(self._new_tab_btn.rect().bottomLeft())
            self._new_tab_menu.exec(pos)

    def _show_about(self) -> None:
        """Show the about dialog."""
        QMessageBox.about(
            self,
            "About Universal Asset Browser",
            "Universal Asset Browser v1\n\n"
            "A cross-DCC asset browser for managing and importing assets.\n\n"
            "Supports local assets and Poly Haven cloud assets.",
        )

    # -------------------------------------------------------------------------
    # Initialization API
    # -------------------------------------------------------------------------

    def initialize(
        self, host_integration: HostIntegration | None = None
    ) -> MainPresenter:
        """
        Initialize the presenter and wire up the application.

        This method creates the MainPresenter, discovers plugins, and sets up
        the full application. Call this after constructing the widget.

        In Houdini, pass the HoudiniIntegration. For standalone/testing,
        pass None to use StandaloneIntegration (or pass it explicitly).

        Args:
            host_integration: The host integration to use. If None, a
                StandaloneIntegration will be created.

        Returns:
            The created MainPresenter instance.

        Raises:
            RuntimeError: If initialize() has already been called.

        Example:
            # Houdini Python Panel
            def onCreateInterface():
                from uab.ui import MainWidget
                from uab.integrations.houdini import HoudiniIntegration

                widget = MainWidget()
                widget.initialize(host_integration=HoudiniIntegration())
                return widget

            # Standalone
            widget = MainWidget()
            presenter = widget.initialize()
        """
        if self._presenter is not None:
            raise RuntimeError("MainWidget.initialize() has already been called")

        # Import here to avoid circular imports and allow presenter to not exist yet
        from uab.presenters.main_presenter import MainPresenter

        # Create default host integration if not provided
        if host_integration is None:
            from uab.integrations.standalone import StandaloneIntegration

            host_integration = StandaloneIntegration()

        # Create and store the presenter
        self._presenter = MainPresenter(view=self, host=host_integration)

        return self._presenter

    @property
    def presenter(self) -> MainPresenter | None:
        """
        The MainPresenter instance, or None if not yet initialized.

        Use initialize() to create the presenter.
        """
        return self._presenter

    @property
    def is_initialized(self) -> bool:
        """Return True if initialize() has been called."""
        return self._presenter is not None
