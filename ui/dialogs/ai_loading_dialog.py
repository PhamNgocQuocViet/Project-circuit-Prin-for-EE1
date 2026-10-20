"""Application-modal AI loading dialog with a font-based spinner."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout


class AILoadingDialog(QDialog):
    """Small modal progress dialog that keeps animating while a worker runs."""

    SPINNER_FRAMES = ("◐", "◓", "◑", "◒")

    def __init__(self, parent=None):
        """Create a modal spinner dialog owned by an optional parent."""
        super().__init__(parent)
        self.setWindowTitle("AI Analysis in Progress")
        self.setWindowModality(Qt.ApplicationModal)
        self.setModal(True)
        self.setFixedSize(420, 200)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._frame_index = 0
        self._allow_close = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(10)

        self.spinner_label = QLabel(self.SPINNER_FRAMES[0])
        self.spinner_label.setAlignment(Qt.AlignCenter)
        spinner_font = QFont("Segoe UI Symbol")
        spinner_font.setPointSize(30)
        self.spinner_label.setFont(spinner_font)
        self.spinner_label.setProperty("role", "loadingSpinner")
        layout.addWidget(self.spinner_label)

        title = QLabel("Waiting for AI Response")
        title.setAlignment(Qt.AlignCenter)
        title.setProperty("role", "sectionTitle")
        layout.addWidget(title)

        message = QLabel(
            "The circuit prompt has been sent.\n\n"
            "Waiting for the AI service to complete the analysis.\n"
            "This may take several seconds or a few minutes."
        )
        message.setAlignment(Qt.AlignCenter)
        message.setWordWrap(True)
        message.setProperty("role", "mutedText")
        layout.addWidget(message)

        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._advance_spinner)

    def showEvent(self, event):
        """Restart animation whenever Qt shows the dialog."""
        super().showEvent(event)
        self._timer.start()

    def closeEvent(self, event):
        """Stop the timer before accepting Qt's close event."""
        if not self._allow_close:
            event.ignore()
            return
        self._timer.stop()
        super().closeEvent(event)

    def finish(self):
        """Allow the dialog to close after the worker has completed."""
        self._allow_close = True
        self.close()

    def stop(self):
        """Stop the spinner and close the dialog after request completion."""
        self._timer.stop()
        self.finish()

    def _advance_spinner(self):
        """Advance the spinner glyph by one frame."""
        self._frame_index = (self._frame_index + 1) % len(self.SPINNER_FRAMES)
        self.spinner_label.setText(self.SPINNER_FRAMES[self._frame_index])
