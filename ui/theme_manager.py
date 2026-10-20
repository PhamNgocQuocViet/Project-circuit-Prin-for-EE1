"""
Application theme management.

The selected mode is stored separately from AI provider settings so changing
appearance never touches provider/model/API-key data.
"""

import os

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QWidget

from app_paths import resource_path


ORGANIZATION = "CircuitPrinciplesAssistant"
APPLICATION = "ApplicationSettings"

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_MODES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)


class ThemeManager:
    """Load, resolve, and apply the application's light/dark QSS themes."""

    SETTINGS_KEY = "appearance/theme_mode"

    @classmethod
    def settings_store(cls):
        """Return the QSettings store used for appearance preferences."""
        return QSettings(QSettings.IniFormat, QSettings.UserScope, ORGANIZATION, APPLICATION)

    @classmethod
    def load_selected_theme(cls):
        """Load a valid saved theme mode, defaulting to system-following."""
        value = cls.settings_store().value(cls.SETTINGS_KEY, THEME_SYSTEM)
        value = str(value).strip().lower()
        if value not in THEME_MODES:
            return THEME_SYSTEM
        return value

    @classmethod
    def save_selected_theme(cls, mode):
        """Normalize and persist a theme mode."""
        mode = cls.normalize_mode(mode)
        store = cls.settings_store()
        store.setValue(cls.SETTINGS_KEY, mode)
        store.sync()

    @staticmethod
    def normalize_mode(mode):
        """Return a supported theme mode for arbitrary stored input."""
        mode = str(mode or THEME_SYSTEM).strip().lower()
        return mode if mode in THEME_MODES else THEME_SYSTEM

    @classmethod
    def resolve_theme(cls, mode=None):
        """Resolve system-following mode to a concrete light or dark theme."""
        mode = cls.normalize_mode(mode or cls.load_selected_theme())
        if mode == THEME_SYSTEM:
            return cls.detect_windows_system_theme()
        return mode

    @staticmethod
    def detect_windows_system_theme():
        """Return the current Windows app theme, falling back to light."""
        if os.name != "nt":
            return THEME_LIGHT
        try:
            import winreg

            path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                value, _value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return THEME_LIGHT if int(value) else THEME_DARK
        except Exception:  # noqa: BLE001 - theme detection must never block launch
            return THEME_LIGHT

    @classmethod
    def stylesheet_path(cls, resolved_theme):
        """Return the packaged QSS path for a concrete theme name."""
        file_name = "dark.qss" if resolved_theme == THEME_DARK else "light.qss"
        return resource_path("ui", "styles", file_name)

    @classmethod
    def load_stylesheet(cls, resolved_theme):
        """Read theme QSS, falling back from a missing dark theme to light."""
        path = cls.stylesheet_path(resolved_theme)
        try:
            with open(path, "r", encoding="utf-8") as stylesheet_file:
                return stylesheet_file.read()
        except OSError:
            if resolved_theme == THEME_DARK:
                return cls.load_stylesheet(THEME_LIGHT)
            return ""

    @classmethod
    def apply_theme(cls, app=None, mode=None, persist=False):
        """Apply a theme to QApplication and notify theme-aware widgets.

        Args:
            app: QApplication to update; defaults to the current instance.
            mode: System, light, or dark theme mode.
            persist: Whether to save mode after applying it.
        """
        app = app or QApplication.instance()
        if app is None:
            return THEME_LIGHT

        selected_mode = cls.normalize_mode(mode or cls.load_selected_theme())
        resolved_theme = cls.resolve_theme(selected_mode)
        app.setProperty("themeMode", selected_mode)
        app.setProperty("resolvedTheme", resolved_theme)
        app.setStyleSheet(cls.load_stylesheet(resolved_theme))
        cls._notify_theme_changed(app, resolved_theme)

        if persist:
            cls.save_selected_theme(selected_mode)
        return resolved_theme

    @staticmethod
    def _notify_theme_changed(app, resolved_theme):
        """Call apply_theme on widgets that expose a theme-refresh hook."""
        for top_level_widget in app.topLevelWidgets():
            for widget in [top_level_widget] + top_level_widget.findChildren(QWidget):
                apply_theme = getattr(widget, "apply_theme", None)
                if callable(apply_theme):
                    apply_theme(resolved_theme)
