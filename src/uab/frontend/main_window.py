from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from uab.frontend.main_widget import MainWidget


class MainWindow(QMainWindow):
    """
    Thin QMainWindow wrapper that hosts the MainWidget as its central widget.
    """

    def __init__(self, main_widget: MainWidget, unregister_callback=None) -> None:
        super().__init__()
        self.setWindowTitle("Universal Asset Browser")
        self.resize(1050, 700)

        # Central widget is now a clean, self-contained MainWidget
        self.main_widget = main_widget
        self.setCentralWidget(main_widget)
        self.unregister_callback = unregister_callback
        self._unregistered = False

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event by unregistering the client.
        This handles when the window is closed by clicking the close button,
        which is different from when the application is quit. """
        self._unregister_if_needed()
        super().closeEvent(event)

    def _unregister_if_needed(self) -> None:
        """Unregister the client if not already unregistered."""
        if self.unregister_callback and not self._unregistered:
            self._unregistered = True
            self.unregister_callback()
