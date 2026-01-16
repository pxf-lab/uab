"""Status bar widget for Universal Asset Browser."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout


class StatusBar(QFrame):
    """
    Status bar widget for displaying system messages and notifications.

    Message types:
    - info: White text (default)
    - warning: Orange text
    - error: Red text
    - success: Green text

    Styles are defined in styles.qss using #statusBar and #statusBarMessage selectors.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set frame shape for styling
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # Set object name for stylesheet targeting
        self.setObjectName("statusBar")

        # Setup layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(0)

        # Message label
        self._message_label = QLabel()
        self._message_label.setObjectName("statusBarMessage")
        layout.addWidget(self._message_label, 1)

        # Set fixed height
        self.setFixedHeight(28)

        # Timer for auto-clearing messages
        self._clear_timer = QTimer(self)
        self._clear_timer.timeout.connect(self.clear)

    def show_message(
        self, message: str, message_type: str = "info", timeout: int = 5000
    ) -> None:
        """
        Display a message in the status bar.

        Args:
            message: The message to display
            message_type: Type of message ('info', 'warning', 'error', 'success')
            timeout: Time in milliseconds before message clears (0 = no auto-clear)
        """
        # Set the message type as a property for stylesheet styling
        self._message_label.setProperty("messageType", message_type)

        # Force style refresh
        self._message_label.style().unpolish(self._message_label)
        self._message_label.style().polish(self._message_label)

        self._message_label.setText(message)

        # Handle auto-clear
        if timeout > 0:
            self._clear_timer.start(timeout)
        else:
            self._clear_timer.stop()

    def clear(self) -> None:
        """Clear the current status message."""
        self._clear_timer.stop()
        self._message_label.setText("")
        self._message_label.setProperty("messageType", "info")
        self._message_label.style().unpolish(self._message_label)
        self._message_label.style().polish(self._message_label)

    def message(self) -> str:
        """Return the current message text."""
        return self._message_label.text()
