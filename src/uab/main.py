"""
Entry point for Universal Asset Browser.

Run with:
    cd src/uab && uv run python main.py

Architecture:
    This module provides two entry points:
    1. create_panel_widget() - For Houdini Python Panels (returns QWidget)
    2. main() - For standalone execution (creates MainWindow)

    Both use the widget-owns-presenter pattern where MainWidget owns the
    MainPresenter via lazy initialization through initialize().
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QWidget

from uab.ui import MainWindow, MainWidget

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
)


def create_panel_widget(host_integration: HostIntegration | None = None) -> QWidget:
    """
    Create and return the main UAB widget for embedding.

    This is the entry point for Houdini Python Panels and other embedded contexts.
    The returned widget owns its presenter, ensuring proper lifetime management.

    Args:
        host_integration: The host integration to use. Pass HoudiniIntegration()
            when running in Houdini, or None for standalone/testing.

    Returns:
        The initialized MainWidget ready for display.

    Example (Houdini Python Panel):
        # In scripts/python/uab_panel.py
        def onCreateInterface():
            from uab.main import create_panel_widget
            from uab.integrations.houdini import HoudiniIntegration
            return create_panel_widget(host_integration=HoudiniIntegration())

    Example (Standalone):
        widget = create_panel_widget()
        widget.show()
    """
    widget = MainWidget()
    widget.initialize(host_integration=host_integration)
    return widget


def main():
    """
    Launch the standalone UAB application.

    This creates the main window, initializes the presenter layer,
    discovers plugins, and starts the Qt event loop.
    """
    app = QApplication.instance() or QApplication(sys.argv)

    window = MainWindow()
    window.initialize()  # Uses StandaloneIntegration by default

    window.show()

    logging.info("UAB launched!")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
