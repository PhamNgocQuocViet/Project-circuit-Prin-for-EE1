"""Appearance settings page."""

from PyQt5.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ui.theme_manager import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, ThemeManager


class AppearanceSettingsPage(QWidget):
    """Theme selection page with immediate preview."""

    THEME_LABELS = {
        THEME_SYSTEM: "System",
        THEME_LIGHT: "Light",
        THEME_DARK: "Dark",
    }

    def __init__(self, parent=None):
        """Build the theme selector and remember the original mode."""
        super().__init__(parent)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Appearance")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        card = QWidget()
        card.setProperty("role", "settingsCard")
        card_layout = QVBoxLayout(card)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.theme_combo = QComboBox()
        for mode in (THEME_SYSTEM, THEME_LIGHT, THEME_DARK):
            self.theme_combo.addItem(self.THEME_LABELS[mode], mode)
        self.theme_combo.currentIndexChanged.connect(self.preview_theme)
        form.addRow("Theme:", self.theme_combo)
        card_layout.addLayout(form)

        helper = QLabel("System follows the Windows app theme. If detection fails, light mode is used.")
        helper.setWordWrap(True)
        helper.setProperty("role", "mutedText")
        card_layout.addWidget(helper)

        layout.addWidget(card)
        layout.addStretch(1)
        self.load_current_settings()

    def load_current_settings(self):
        """Reload the saved theme and update the selector without previewing."""
        self._loading = True
        selected = ThemeManager.load_selected_theme()
        index = self.theme_combo.findData(selected)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self._loading = False

    def selected_theme(self):
        """Return the theme mode stored by the selected combo-box row."""
        return self.theme_combo.currentData()

    def preview_theme(self):
        """Apply the selected theme temporarily without persisting it."""
        if self._loading:
            return
        ThemeManager.apply_theme(mode=self.selected_theme(), persist=False)

    def apply_settings(self):
        """Apply and persist the selected theme, then update rollback state."""
        ThemeManager.apply_theme(mode=self.selected_theme(), persist=True)
