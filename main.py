"""Start the Electrical Engineering Learning App.

This module creates the Qt application, applies the saved theme, constructs the
main window, and transfers control to Qt's event loop. It contains no circuit
or settings logic of its own.
"""

import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.theme_manager import ThemeManager

def main():
    """Create and run the desktop application until the main window closes."""
    app = QApplication(sys.argv)
    ThemeManager.apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
