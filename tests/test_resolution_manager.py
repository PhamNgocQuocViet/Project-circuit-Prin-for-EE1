"""Regression tests for display presets, resizing, and overlay drawer layout."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtWidgets import QApplication, QListWidgetItem
from unittest.mock import patch

from ui.resolution_manager import ResolutionManager
from ui.main_window import ComponentListWidget, MainWindow
from ui.settings_pages.general_settings_page import GeneralSettingsPage


class FakeScreen:
    def __init__(self, width, height, device_pixel_ratio=1.0):
        self._geometry = QRect(0, 0, width, height)
        self._device_pixel_ratio = device_pixel_ratio

    def geometry(self):
        return self._geometry

    def devicePixelRatio(self):
        return self._device_pixel_ratio


class ResolutionManagerTests(unittest.TestCase):
    def test_1080p_display_only_exposes_720p_and_1080p(self):
        presets = ResolutionManager.supported_presets(FakeScreen(1920, 1080))
        self.assertEqual([preset.key for preset in presets], ["720p", "1080p"])

    def test_high_dpi_4k_display_uses_physical_pixels(self):
        screen = FakeScreen(2560, 1440, device_pixel_ratio=1.5)
        presets = ResolutionManager.supported_presets(screen)
        self.assertEqual(
            [preset.key for preset in presets], ["720p", "1080p", "2k", "4k"]
        )

    def test_unavailable_saved_resolution_falls_back_to_highest_supported(self):
        preset = ResolutionManager.resolved_preset(FakeScreen(1920, 1080), "8k")
        self.assertEqual(preset.key, "1080p")

    def test_sub_720p_display_has_no_selectable_standard_preset(self):
        self.assertEqual(ResolutionManager.supported_presets(FakeScreen(1024, 600)), [])


class ComponentListSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_minimum_height_reserves_four_visible_rows(self):
        component_list = ComponentListWidget()
        for index in range(6):
            component_list.addItem(QListWidgetItem(f"Component {index}"))

        component_list.lock_minimum_visible_rows()

        required_rows_height = sum(
            max(component_list.sizeHintForRow(row), component_list.fontMetrics().height() + 16)
            for row in range(4)
        )
        self.assertGreaterEqual(
            component_list.minimumHeight(),
            required_rows_height + (2 * component_list.frameWidth()),
        )


class ResolutionApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_general_page_applies_resolution_synchronously(self):
        class FakeMainWindow(ComponentListWidget):
            def __init__(self):
                super().__init__()
                self.applied_key = None

            def apply_resolution_preset(self, key):
                self.applied_key = key

        main_window = FakeMainWindow()
        settings_container = ComponentListWidget(main_window)
        screen = FakeScreen(1920, 1080)
        with (
            patch.object(ResolutionManager, "screen_for_window", return_value=screen),
            patch.object(ResolutionManager, "load_selected_resolution", return_value="720p"),
            patch.object(ResolutionManager, "save_selected_resolution") as save_resolution,
        ):
            page = GeneralSettingsPage(settings_container)
            page.resolution_combo.setCurrentIndex(page.resolution_combo.findData("1080p"))
            page.apply_settings()

        self.assertEqual(main_window.applied_key, "1080p")
        save_resolution.assert_called_once_with("1080p")
        page.close()
        settings_container.close()
        main_window.close()

    def test_full_screen_restores_resizable_window_and_keeps_overlay_drawer_widths(self):
        window = MainWindow()
        window.show()
        self.app.processEvents()

        window.enter_full_screen()
        self.app.processEvents()
        self.assertTrue(window.isFullScreen())
        self.assertEqual(window.component_panel.width(), window.COMPONENT_DRAWER_WIDTH)
        self.assertEqual(window.value_panel.width(), window.VALUE_DRAWER_WIDTH)
        self.assertEqual(
            window.value_panel.geometry().right(),
            window.workspace.width() - 1,
        )

        window.exit_full_screen()
        self.app.processEvents()
        self.assertFalse(window.isFullScreen())
        self.assertNotEqual(window.minimumSize(), window.maximumSize())
        self.assertTrue(bool(window.windowFlags() & Qt.WindowMaximizeButtonHint))
        window.close()

    def test_720p_overlay_drawers_fit_workspace_without_overlap(self):
        window = MainWindow()
        window.setMinimumSize(1280, 720)
        window.resize(1280, 720)
        window.show()
        window.toggle_component_drawer()
        self.app.processEvents()

        self.assertEqual(window.component_panel.height(), window.workspace.height())
        self.assertEqual(window.component_panel.width(), window.COMPONENT_DRAWER_WIDTH)
        self.assertLess(
            window.component_tabs.geometry().bottom(),
            window.comment_browser.geometry().top(),
        )

        window.toggle_value_drawer()
        self.app.processEvents()
        self.assertFalse(window.component_panel.isVisible())
        self.assertTrue(window.value_panel.isVisible())
        self.assertEqual(window.value_panel.height(), window.workspace.height())
        self.assertEqual(window.value_panel.width(), window.VALUE_DRAWER_WIDTH)
        window.close()


if __name__ == "__main__":
    unittest.main()
