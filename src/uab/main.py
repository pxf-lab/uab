"""
Entry point and test launcher for Universal Asset Browser.

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

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QWidget

from uab.core.models import StandardAsset, AssetStatus, AssetType
from uab.ui import MainWindow, MainWidget, BrowserView

if TYPE_CHECKING:
    from uab.core.interfaces import HostIntegration


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


# =============================================================================
# Test/Development Support (Phase 2 - before presenters exist)
# =============================================================================
# The functions below provide manual UI testing before the presenter layer
# is implemented. Once Phase 3 (Presenter Layer) is complete, main() will
# use create_panel_widget() or window.initialize() instead.


def create_mock_assets() -> list[StandardAsset]:
    """Create mock assets for testing the UI."""
    hdri_dir = Path("/Users/dev/Downloads/test_hdris")

    return [
        StandardAsset(
            id="test-1",
            source="local",
            external_id="afrikaans_church_interior",
            name="Afrikaans Church Interior",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "afrikaans_church_interior_1k.hdr",
        ),
        StandardAsset(
            id="test-2",
            source="local",
            external_id="autumn_field",
            name="Autumn Field",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "autumn_field_1k.hdr",
        ),
        StandardAsset(
            id="test-3",
            source="local",
            external_id="autumn_hill_view",
            name="Autumn Hill View",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "autumn_hill_view_1k.hdr",
        ),
        StandardAsset(
            id="test-4",
            source="local",
            external_id="golden_gate_hills",
            name="Golden Gate Hills",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "golden_gate_hills_1k.hdr",
        ),
        StandardAsset(
            id="test-5",
            source="local",
            external_id="horn_koppe_spring",
            name="Horn Koppe Spring",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "horn-koppe_spring_1k.hdr",
        ),
        StandardAsset(
            id="test-6",
            source="local",
            external_id="plac_wolnosci",
            name="Plac Wolnosci",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "plac_wolnosci_1k.hdr",
        ),
        StandardAsset(
            id="test-7",
            source="local",
            external_id="plains_sunset",
            name="Plains Sunset",
            type=AssetType.HDRI,
            status=AssetStatus.LOCAL,
            local_path=hdri_dir / "plains_sunset_1k.exr",
        ),
        # Keep a couple cloud/downloading examples for UI testing
        StandardAsset(
            id="test-8",
            source="polyhaven",
            external_id="studio_small",
            name="Studio Small (Cloud)",
            type=AssetType.HDRI,
            status=AssetStatus.CLOUD,
        ),
        StandardAsset(
            id="test-9",
            source="polyhaven",
            external_id="mossy_rock",
            name="Mossy Rock (Downloading)",
            type=AssetType.TEXTURE,
            status=AssetStatus.DOWNLOADING,
        ),
    ]


def create_browser_with_signals(assets: list[StandardAsset]) -> BrowserView:
    """Create a browser view with connected signals for testing."""
    browser = BrowserView()
    browser.set_items(assets)
    browser.set_renderers(["Arnold", "Redshift", "Karma"])

    # Connect signals for testing
    browser.search_requested.connect(lambda q: print(f"Search: {q}"))
    browser.detail_requested.connect(lambda id: print(f"Detail: {id}"))
    browser.import_requested.connect(lambda id: print(f"Import: {id}"))
    browser.download_requested.connect(lambda id: print(f"Download: {id}"))
    browser.remove_requested.connect(lambda id: print(f"Remove: {id}"))

    return browser


def main():
    """
    Launch the standalone test UI.

    NOTE: This is a temporary test harness for Phase 2 (UI development).
    Once Phase 3 (Presenter Layer) is complete, this will be simplified to:

        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow()
        window.initialize()  # Creates presenter, discovers plugins, etc.
        window.show()
        sys.exit(app.exec())
    """
    app = QApplication.instance() or QApplication(sys.argv)

    # Create main window (not yet initialized - manual testing mode)
    window = MainWindow()

    # ==========================================================================
    # Manual UI testing (Phase 2) - bypasses presenter layer
    # This section will be removed once presenters are implemented
    # ==========================================================================

    # Get all mock assets
    all_assets = create_mock_assets()

    # Split assets for different tabs
    local_assets = [a for a in all_assets if a.source == "local"]
    polyhaven_assets = [a for a in all_assets if a.source == "polyhaven"]

    # Create Local Library tab
    local_browser = create_browser_with_signals(local_assets)
    window.add_tab(local_browser, "Local Library")

    # Create Poly Haven tab
    polyhaven_browser = create_browser_with_signals(polyhaven_assets)
    window.add_tab(polyhaven_browser, "Poly Haven")

    # Populate new tab menu with mock plugins
    window.populate_new_tab_menu({
        "local": "Local Library",
        "polyhaven": "Poly Haven",
    })

    # ==========================================================================
    # End manual testing section
    # ==========================================================================

    window.show()

    print("UI launched! Try:")
    print("  - Type in search bar (debounced)")
    print("  - Double-click an asset to see detail panel")
    print("  - Right-click for context menu")
    print("  - Ctrl+scroll to zoom")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
