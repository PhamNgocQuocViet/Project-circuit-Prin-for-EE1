"""General modular settings dialog."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QSizePolicy, QStackedWidget, QVBoxLayout,
)

from ui.settings_pages.about_page import AboutPage
from ui.settings_pages.ai_settings_page import AISettingsPage
from ui.settings_pages.appearance_settings_page import AppearanceSettingsPage
from ui.settings_pages.general_settings_page import GeneralSettingsPage
from ui.theme_manager import ThemeManager


class SettingsDialog(QDialog):
    """Settings dialog with navigation list and stacked pages."""

    def __init__(self, parent=None):
        """Construct navigation and all modular settings pages."""
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(760, 460)
        self.setMinimumSize(660, 390)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._original_theme = ThemeManager.load_selected_theme()

        root_layout = QVBoxLayout(self)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(14)

        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.navigation.setFixedWidth(160)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_layout.addWidget(self.navigation)

        self.stack = QStackedWidget()
        body_layout.addWidget(self.stack, 1)
        root_layout.addLayout(body_layout, 1)

        self.pages = []
        self._add_page("AI", AISettingsPage(self))
        self._add_page("Appearance", AppearanceSettingsPage(self))
        self._add_page("General", GeneralSettingsPage(self))
        self._add_page("About", AboutPage(self))

        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.Apply).clicked.connect(self.apply_pages)
        root_layout.addWidget(self.button_box)

    def _add_page(self, title, page):
        """Add a titled navigation item and its corresponding page widget."""
        item = QListWidgetItem(title)
        item.setSizeHint(item.sizeHint())
        self.navigation.addItem(item)
        self.stack.addWidget(page)
        self.pages.append(page)

    def apply_pages(self):
        """Apply every page that exposes an apply_settings hook."""
        try:
            for page in self.pages:
                apply_settings = getattr(page, "apply_settings", None)
                if apply_settings is not None:
                    apply_settings()
        except Exception as exc:  # noqa: BLE001 - keep settings errors visible
            QMessageBox.critical(self, "Settings Error", f"Could not save settings:\n{exc}")
            return False
        self._original_theme = ThemeManager.load_selected_theme()
        return True

    def accept(self):
        """Apply pending settings before closing with Accepted status."""
        if self.apply_pages():
            super().accept()

    def reject(self):
        """Restore previewed appearance and close without saving changes."""
        ThemeManager.apply_theme(mode=self._original_theme, persist=False)
        super().reject()
