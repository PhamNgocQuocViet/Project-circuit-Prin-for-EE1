"""Regression tests for analysis modes, solving-method choices, and dialogs."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from ai_assistant.analysis_dialog import AnalysisDialog
from ai_assistant.analysis_request import AnalysisMode, AnalysisRequest, SolvingMethod
from ai_assistant.prompt_builder import build_ai_prompt
from ai_assistant.result_dialog import ResultDialog
from components.electrical_component import ComponentType


class FakeComponent:
    def __init__(self, reference_name, comp_type, assigned_value="1"):
        self.reference_name = reference_name
        self.comp_type = comp_type
        self.assigned_value = assigned_value


class AnalysisOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preferred_method_is_added_to_targeted_prompt(self):
        request = AnalysisRequest(
            mode=AnalysisMode.COMPONENT_ANALYSIS,
            target_component="R#1",
            target_component_type=ComponentType.RESISTOR,
            requested_quantity="Current",
            preferred_method=SolvingMethod.MESH,
        )
        prompt = build_ai_prompt("Circuit:\nR1", request)
        self.assertIn("Use Mesh Analysis as the solving method.", prompt)
        self.assertIn("<EXPLANATION>", prompt)

    def test_auto_method_asks_ai_to_select_suitable_method(self):
        request = AnalysisRequest(
            mode=AnalysisMode.COMPONENT_ANALYSIS,
            target_component="R#1",
            target_component_type=ComponentType.RESISTOR,
            requested_quantity="Current",
            preferred_method=SolvingMethod.AUTO,
        )
        prompt = build_ai_prompt("Circuit:\nR1", request)
        self.assertIn("Select the most suitable solving method automatically.", prompt)

    def test_user_defined_method_is_added_to_prompt(self):
        request = AnalysisRequest(
            mode=AnalysisMode.COMPONENT_ANALYSIS,
            target_component="R#1",
            target_component_type=ComponentType.RESISTOR,
            requested_quantity="Current",
            preferred_method=SolvingMethod.USER_DEFINED,
            custom_method="Modified nodal analysis with a supernode",
        )
        prompt = build_ai_prompt("Circuit:\nR1", request)
        self.assertIn(
            "Use this user-defined solving method: Modified nodal analysis with a supernode",
            prompt,
        )

    def test_empty_user_defined_method_is_rejected_by_request(self):
        request = AnalysisRequest(
            mode=AnalysisMode.COMPONENT_ANALYSIS,
            target_component="R#1",
            target_component_type=ComponentType.RESISTOR,
            requested_quantity="Current",
            preferred_method=SolvingMethod.USER_DEFINED,
        )
        with self.assertRaisesRegex(ValueError, "custom solving method"):
            request.to_prompt_section()

    def test_full_analysis_prompt_requests_results_only(self):
        request = AnalysisRequest(mode=AnalysisMode.FULL_ANALYSIS)
        prompt = build_ai_prompt("Circuit:\nR1", request)
        self.assertIn("Return results only", prompt)
        self.assertIn("Do not return an EXPLANATION section", prompt)
        self.assertNotIn("<EXPLANATION>", prompt)
        self.assertNotIn("Textbook-style explanation rules", prompt)
        self.assertNotIn("Show the original circuit equations", prompt)

    def test_method_selector_only_visible_for_modes_two_and_three(self):
        component = FakeComponent("R#1", ComponentType.RESISTOR, assigned_value="")
        dialog = AnalysisDialog([component], lambda item: item.reference_name)
        dialog.show()
        self.app.processEvents()

        dialog.mode_combo.setCurrentIndex(0)
        self.assertFalse(dialog.method_combo.isVisible())
        self.assertFalse(dialog.custom_method_input.isVisible())

        dialog.mode_combo.setCurrentIndex(1)
        self.assertTrue(dialog.method_combo.isVisible())
        self.assertFalse(dialog.custom_method_input.isVisible())

        dialog.mode_combo.setCurrentIndex(2)
        self.assertTrue(dialog.method_combo.isVisible())
        self.assertFalse(dialog.custom_method_input.isVisible())
        dialog.close()

    def test_user_defined_selection_reveals_text_box_and_stores_text(self):
        component = FakeComponent("R#1", ComponentType.RESISTOR, assigned_value="")
        dialog = AnalysisDialog([component], lambda item: item.reference_name)
        dialog.show()
        dialog.mode_combo.setCurrentIndex(1)
        dialog.method_combo.setCurrentIndex(dialog.method_combo.findData(SolvingMethod.USER_DEFINED))
        self.app.processEvents()
        self.assertTrue(dialog.custom_method_input.isVisible())

        dialog.custom_method_input.setText("Source transformation followed by KCL")
        dialog._on_continue()

        self.assertEqual(dialog.result_request.preferred_method, SolvingMethod.USER_DEFINED)
        self.assertEqual(dialog.result_request.custom_method, "Source transformation followed by KCL")
        dialog.close()

    def test_custom_method_editor_has_full_height_and_does_not_overlap_next_row(self):
        component = FakeComponent("R#1", ComponentType.RESISTOR, assigned_value="")
        dialog = AnalysisDialog([component], lambda item: item.reference_name)
        dialog.show()
        dialog.mode_combo.setCurrentIndex(1)
        dialog.method_combo.setCurrentIndex(
            dialog.method_combo.findData(SolvingMethod.USER_DEFINED)
        )
        self.app.processEvents()

        self.assertGreaterEqual(dialog.custom_method_input.height(), 34)
        self.assertLess(
            dialog.custom_method_input.geometry().bottom(),
            dialog.component_combo.geometry().top(),
        )
        self.assertGreaterEqual(dialog.custom_method_input.width(), 300)
        dialog.close()

    def test_selected_method_is_stored_in_analysis_request(self):
        component = FakeComponent("R#1", ComponentType.RESISTOR, assigned_value="")
        dialog = AnalysisDialog([component], lambda item: item.reference_name)
        dialog.mode_combo.setCurrentIndex(1)
        dialog.method_combo.setCurrentIndex(dialog.method_combo.findData(SolvingMethod.SUPERPOSITION))

        dialog._on_continue()

        self.assertEqual(dialog.result_request.preferred_method, SolvingMethod.SUPERPOSITION)
        dialog.close()

    def test_full_analysis_result_has_no_explanation_tab(self):
        with patch("ai_assistant.markdown_viewer.QWebEngineView", None):
            dialog = ResultDialog("VA = 1.0000 V", "Hidden derivation", show_explanation=False)
        self.assertEqual(dialog.tabs.count(), 1)
        self.assertEqual(dialog.tabs.tabText(0), "Solution")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
