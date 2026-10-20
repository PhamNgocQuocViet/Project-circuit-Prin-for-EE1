"""General application settings."""

from PyQt5.QtWidgets import QApplication, QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ui.resolution_manager import ResolutionManager


class GeneralSettingsPage(QWidget):
    """General settings, including the application window-size preset."""

    def __init__(self, parent=None):
        """Build the resolution selector for the parent's active screen."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("General")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        card = QWidget()
        card.setProperty("role", "settingsCard")
        card_layout = QVBoxLayout(card)

        self.screen = ResolutionManager.screen_for_window(self._main_window())
        pixel_size = ResolutionManager.screen_pixel_size(self.screen)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.resolution_combo = QComboBox()
        supported = ResolutionManager.supported_presets(self.screen)
        for preset in supported:
            self.resolution_combo.addItem(preset.label, preset.key)
        form.addRow("Resolution:", self.resolution_combo)
        card_layout.addLayout(form)

        if supported:
            selected = ResolutionManager.resolved_preset(
                self.screen, ResolutionManager.load_selected_resolution()
            )
            selected_index = self.resolution_combo.findData(selected.key)
            self.resolution_combo.setCurrentIndex(max(selected_index, 0))
            helper_text = (
                f"Detected display: {pixel_size.width()} x {pixel_size.height()} pixels. "
                "Only resolutions supported by this display are listed. "
                "A preset sets the window size; it can then be resized or maximized while "
                "the main regions remain proportional."
            )
        else:
            self.resolution_combo.setEnabled(False)
            helper_text = (
                f"Detected display: {pixel_size.width()} x {pixel_size.height()} pixels. "
                "No standard 720p-or-higher preset fits this display, so the app uses "
                "the largest safe 16:9 starting size available."
            )

        text = QLabel(helper_text)
        text.setWordWrap(True)
        text.setProperty("role", "mutedText")
        card_layout.addWidget(text)

        layout.addWidget(card)
        layout.addStretch(1)

    def apply_settings(self):
        """Persist and immediately apply the selected resolution preset."""
        key = self.resolution_combo.currentData()
        if key is None:
            return
        ResolutionManager.save_selected_resolution(key)
        main_window = self._main_window()
        if main_window is not None:
            apply_resolution = getattr(main_window, "apply_resolution_preset", None)
            if callable(apply_resolution):
                apply_resolution(key)
                QApplication.processEvents()

    def _main_window(self):
        """Walk parent widgets to find one supporting resolution changes."""
        settings_dialog = self.parentWidget()
        return settings_dialog.parentWidget() if settings_dialog is not None else None
