"""Regression checks for the canvas-first main-window workflows."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication, QListWidgetItem

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from components.electrical_component import ComponentType
from ui.main_window import MainWindow


class MainWindowWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_toolbar_omits_manual_analyze_and_rotate_actions(self):
        button_texts = {
            button.text() for button in self.window.top_toolbar.findChildren(type(self.window.add_component_button))
        }
        self.assertNotIn("✓ Analyze", button_texts)
        self.assertNotIn("⟳ Rotate", button_texts)
        self.assertFalse(hasattr(self.window, "analyze_btn"))
        self.assertFalse(hasattr(self.window, "rotate_btn"))

    def test_empty_component_categories_are_hidden_and_restore_automatically(self):
        self.assertEqual(self.window.component_tabs.count(), 1)
        self.assertEqual(self.window.component_tabs.tabText(0), "Basic")

        self.window.electronics_component_list.addItem(QListWidgetItem("Diode"))
        self.window._sync_visible_component_tabs()
        self.assertEqual(
            [
                self.window.component_tabs.tabText(index)
                for index in range(self.window.component_tabs.count())
            ],
            ["Basic", "Electronics"],
        )

        self.window.electronics_component_list.clear()
        self.window._sync_visible_component_tabs()
        self.assertEqual(self.window.component_tabs.count(), 1)

    def test_component_lifecycle_keeps_values_and_live_comments_in_sync(self):
        component = self.window.canvas.place_component(ComponentType.RESISTOR, QPointF(0, 0))

        self.assertIn(component, self.window.component_value_widgets)
        self.assertIn("R#1", self.window.comment_browser.toPlainText())

        self.window.canvas.set_drag_selected_component(component)
        self.window.delete_selected_component_from_toolbar()

        self.assertNotIn(component, self.window.canvas.components)
        self.assertNotIn(component, self.window.component_value_widgets)
        self.assertIn("All component values are entered", self.window.comment_browser.toPlainText())

    def test_clear_resets_component_references_and_value_widgets(self):
        first = self.window.canvas.place_component(ComponentType.RESISTOR, QPointF(0, 0))
        self.assertEqual(first.reference_name, "R#1")

        self.window.clear_canvas_from_toolbar()
        replacement = self.window.canvas.place_component(ComponentType.RESISTOR, QPointF(40, 0))

        self.assertEqual(replacement.reference_name, "R#1")
        self.assertEqual(len(self.window.component_value_widgets), 1)


if __name__ == "__main__":
    unittest.main()
