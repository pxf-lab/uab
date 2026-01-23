from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


# Mock PySide6 before any imports that depend on it

def _setup_pyside6_mock():
    """Set up mock PySide6 modules for testing without Qt dependency."""
    from types import ModuleType

    # Create mock modules as proper ModuleType instances
    mock_pyside6 = ModuleType("PySide6")
    mock_qt_core = ModuleType("PySide6.QtCore")
    mock_qt_gui = ModuleType("PySide6.QtGui")
    mock_qt_widgets = ModuleType("PySide6.QtWidgets")

    class MockQObject:
        def __init__(self, parent=None):
            pass

    class MockSignal:
        def __init__(self, *args):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args):
            for cb in self._callbacks:
                cb(*args)

    # QThread mock that can be subclassed
    class MockQThread:
        def __init__(self, parent=None):
            pass

        def start(self):
            pass

        def wait(self, timeout=None):
            return True

        def deleteLater(self):
            pass

    class MockQMutex:
        def __init__(self):
            pass

        def lock(self):
            pass

        def unlock(self):
            pass

    # QtCore classes
    mock_qt_core.QObject = MockQObject
    mock_qt_core.Signal = MockSignal
    mock_qt_core.Slot = lambda *args: lambda fn: fn  # Decorator that does nothing
    mock_qt_core.QTimer = MagicMock()
    mock_qt_core.Qt = MagicMock()
    mock_qt_core.QSize = MagicMock()
    mock_qt_core.QEvent = MagicMock()
    mock_qt_core.QThread = MockQThread
    mock_qt_core.QMutex = MockQMutex
    mock_qt_core.QModelIndex = MagicMock()

    # QtGui classes
    mock_qt_gui.QWheelEvent = MagicMock()
    mock_qt_gui.QPixmap = MagicMock()
    mock_qt_gui.QStandardItemModel = MagicMock()
    mock_qt_gui.QStandardItem = MagicMock()
    mock_qt_gui.QShowEvent = MagicMock()

    # QtWidgets classes
    mock_qt_widgets.QWidget = MagicMock()
    mock_qt_widgets.QDialog = MagicMock()
    mock_qt_widgets.QFileDialog = MagicMock()
    mock_qt_widgets.QFormLayout = MagicMock()
    mock_qt_widgets.QVBoxLayout = MagicMock()
    mock_qt_widgets.QHBoxLayout = MagicMock()
    mock_qt_widgets.QComboBox = MagicMock()
    mock_qt_widgets.QLineEdit = MagicMock()
    mock_qt_widgets.QCheckBox = MagicMock()
    mock_qt_widgets.QDialogButtonBox = MagicMock()
    mock_qt_widgets.QMessageBox = MagicMock()
    mock_qt_widgets.QListView = MagicMock()
    mock_qt_widgets.QLabel = MagicMock()
    mock_qt_widgets.QSplitter = MagicMock()
    mock_qt_widgets.QProgressBar = MagicMock()
    mock_qt_widgets.QMenu = MagicMock()
    mock_qt_widgets.QPushButton = MagicMock()
    mock_qt_widgets.QScrollArea = MagicMock()
    mock_qt_widgets.QFrame = MagicMock()
    mock_qt_widgets.QSizePolicy = MagicMock()
    mock_qt_widgets.QStyledItemDelegate = MagicMock()
    mock_qt_widgets.QStyleOptionViewItem = MagicMock()
    mock_qt_widgets.QApplication = MagicMock()
    mock_qt_widgets.QStackedWidget = MagicMock()

    # Wire up submodules
    mock_pyside6.QtCore = mock_qt_core
    mock_pyside6.QtGui = mock_qt_gui
    mock_pyside6.QtWidgets = mock_qt_widgets

    # Register mock modules
    sys.modules["PySide6"] = mock_pyside6
    sys.modules["PySide6.QtCore"] = mock_qt_core
    sys.modules["PySide6.QtGui"] = mock_qt_gui
    sys.modules["PySide6.QtWidgets"] = mock_qt_widgets


# Apply the mock before any test imports
_setup_pyside6_mock()


# Pre-import ui modules so they exist for patching

def _setup_ui_mocks():
    """Pre-import UI modules so they exist for patching."""
    try:
        import uab.ui
        import uab.ui.browser
        import uab.ui.delegates
    except ImportError as e:
        # If imports fail for other reasons, create mock modules
        from types import ModuleType

        if "uab.ui" not in sys.modules:
            mock_ui = ModuleType("uab.ui")
            sys.modules["uab.ui"] = mock_ui

        if "uab.ui.browser" not in sys.modules:
            mock_browser = ModuleType("uab.ui.browser")
            mock_browser.BrowserView = MagicMock()
            sys.modules["uab.ui.browser"] = mock_browser

        if "uab.ui.delegates" not in sys.modules:
            mock_delegates = ModuleType("uab.ui.delegates")
            mock_delegates.AssetDelegate = MagicMock()
            sys.modules["uab.ui.delegates"] = mock_delegates


_setup_ui_mocks()


@pytest.fixture
def make_asset(tmp_path: Path) -> Callable[..., StandardAsset]:
    from uab.core.models import AssetStatus, AssetType, StandardAsset

    def _make(**overrides):
        # Create a unique directory for this specific asset creation
        # to ensure no collisions between multiple assets in one test.
        asset_dir = tmp_path / overrides.get("external_id", "default_id")
        asset_dir.mkdir(exist_ok=True)

        data = {
            "id": "",
            "source": "local",
            "external_id": "brick_01",
            "name": "Brick",
            "type": AssetType.TEXTURE,
            "status": AssetStatus.LOCAL,
            "local_path": asset_dir / "brick",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "thumbnail_path": asset_dir / "thumb.jpg",
            "metadata": {"files": {"diffuse": "brick_diffuse.png"}},
        }
        data.update(overrides)
        return StandardAsset(**data)

    return _make
