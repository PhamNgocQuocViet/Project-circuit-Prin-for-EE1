"""Application resolution presets and display capability detection."""

from dataclasses import dataclass

from PyQt5.QtCore import QSettings, QSize
from PyQt5.QtWidgets import QApplication

from ui.theme_manager import APPLICATION, ORGANIZATION


@dataclass(frozen=True)
class ResolutionPreset:
    """One selectable 16:9 application resolution."""

    key: str
    name: str
    width: int
    height: int

    @property
    def label(self):
        """Return the display label shown in General settings."""
        return f"{self.name} ({self.width} x {self.height})"


RESOLUTION_PRESETS = (
    ResolutionPreset("720p", "720p HD", 1280, 720),
    ResolutionPreset("1080p", "1080p Full HD", 1920, 1080),
    ResolutionPreset("2k", "2K QHD", 2560, 1440),
    ResolutionPreset("4k", "4K UHD", 3840, 2160),
    ResolutionPreset("8k", "8K UHD", 7680, 4320),
)


class ResolutionManager:
    """Persist, validate, and apply application window-size presets."""

    SETTINGS_KEY = "general/resolution"
    DEFAULT_KEY = "720p"

    @classmethod
    def settings_store(cls):
        """Return the QSettings store used for general application options."""
        return QSettings(QSettings.IniFormat, QSettings.UserScope, ORGANIZATION, APPLICATION)

    @classmethod
    def load_selected_resolution(cls):
        """Load a valid saved preset key, falling back to 720p."""
        value = str(cls.settings_store().value(cls.SETTINGS_KEY, cls.DEFAULT_KEY)).strip().lower()
        return value if cls.preset_for_key(value) is not None else cls.DEFAULT_KEY

    @classmethod
    def save_selected_resolution(cls, key):
        """Persist a validated resolution preset key.

        Args:
            key: Key from RESOLUTION_PRESETS, such as ``"1080p"``.
        """
        if cls.preset_for_key(key) is None:
            raise ValueError(f"Unknown resolution preset: {key}")
        store = cls.settings_store()
        store.setValue(cls.SETTINGS_KEY, key)
        store.sync()

    @staticmethod
    def preset_for_key(key):
        """Return the preset matching key, or None for an unknown key."""
        normalized = str(key or "").strip().lower()
        return next((preset for preset in RESOLUTION_PRESETS if preset.key == normalized), None)

    @staticmethod
    def screen_pixel_size(screen):
        """Return physical display pixels even when Qt high-DPI scaling is active."""
        if screen is None:
            return QSize()
        geometry = screen.geometry()
        ratio = max(float(screen.devicePixelRatio()), 1.0)
        return QSize(round(geometry.width() * ratio), round(geometry.height() * ratio))

    @classmethod
    def supported_presets(cls, screen):
        """Return presets that fit within a screen's physical pixel size."""
        pixel_size = cls.screen_pixel_size(screen)
        return [
            preset
            for preset in RESOLUTION_PRESETS
            if preset.width <= pixel_size.width() and preset.height <= pixel_size.height()
        ]

    @staticmethod
    def screen_for_window(window=None):
        """Resolve the screen containing window, or the primary screen."""
        app = QApplication.instance()
        if app is None:
            return None

        if window is not None:
            handle = window.windowHandle()
            if handle is not None and handle.screen() is not None:
                return handle.screen()
            screen_at = getattr(app, "screenAt", None)
            if callable(screen_at):
                screen = screen_at(window.frameGeometry().center())
                if screen is not None:
                    return screen
        return app.primaryScreen()

    @classmethod
    def resolved_preset(cls, screen, requested_key=None):
        """Resolve a requested key to the closest supported preset."""
        supported = cls.supported_presets(screen)
        if not supported:
            return None
        requested = cls.preset_for_key(requested_key or cls.load_selected_resolution())
        return requested if requested in supported else supported[-1]

    @classmethod
    def apply_to_window(cls, window, requested_key=None):
        """Apply a supported target size and a safe DPI-aware minimum size."""
        screen = cls.screen_for_window(window)
        preset = cls.resolved_preset(screen, requested_key)
        if screen is None:
            return None

        ratio = max(float(screen.devicePixelRatio()), 1.0)
        if preset is not None:
            logical_size = QSize(round(preset.width / ratio), round(preset.height / ratio))
            applied_key = preset.key
        else:
            # Very small/legacy displays cannot expose a standard preset. Start
            # with a fitted 16:9 window while retaining normal resize behavior.
            bounds = screen.geometry().size()
            width = min(bounds.width(), round(bounds.height() * 16 / 9))
            height = round(width * 9 / 16)
            logical_size = QSize(max(width, 1), max(height, 1))
            applied_key = None

        supported = cls.supported_presets(screen)
        if supported:
            smallest = supported[0]
            minimum_size = QSize(
                round(smallest.width / ratio), round(smallest.height / ratio)
            )
        else:
            minimum_size = logical_size

        window.setMinimumSize(minimum_size)
        window.setMaximumSize(16777215, 16777215)
        window.resize(logical_size)
        geometry = screen.geometry()
        window.move(
            geometry.x() + (geometry.width() - logical_size.width()) // 2,
            geometry.y() + (geometry.height() - logical_size.height()) // 2,
        )
        return applied_key
