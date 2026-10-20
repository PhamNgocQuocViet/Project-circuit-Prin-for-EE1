"""Regression tests for engineering-unit selection, export, and persistence."""

import unittest

from ai_assistant.circuit_translator import _format_value
from circuit_engine.io.circuit_serializer import serialize_circuit
from components.electrical_component import ComponentType
from components.unit_scales import normalize_unit_symbol, options_for_component


class FakeComponent:
    def __init__(self, comp_type, value="", unit=""):
        self.comp_type = comp_type
        self.assigned_value = value
        self.value_unit = unit
        self.reference_name = "R#1"
        self.display_name = "Resistor #1"
        self.grid_x = 1
        self.grid_y = 2
        self.rotation_angle = 0


class ComponentUnitTests(unittest.TestCase):
    def test_resistor_has_milli_base_kilo_and_mega_scales(self):
        symbols = [option.symbol for option in options_for_component(ComponentType.RESISTOR)]
        self.assertEqual(symbols, ["mΩ", "Ω", "kΩ", "MΩ"])

    def test_legacy_unit_label_normalizes_to_base_symbol(self):
        self.assertEqual(normalize_unit_symbol(ComponentType.RESISTOR, "Ohm (Ω)"), "Ω")

    def test_unknown_or_missing_unit_falls_back_to_base_unit(self):
        self.assertEqual(normalize_unit_symbol(ComponentType.CAPACITOR, ""), "F")
        self.assertEqual(normalize_unit_symbol(ComponentType.INDUCTOR, "invalid"), "H")

    def test_ai_export_preserves_selected_scale(self):
        component = FakeComponent(ComponentType.RESISTOR, "7", "kΩ")
        self.assertEqual(_format_value(component), "7 kΩ")

    def test_serialization_persists_selected_unit(self):
        component = FakeComponent(ComponentType.RESISTOR, "7", "kΩ")
        data = serialize_circuit([component])
        self.assertEqual(data["components"][0]["value_unit"], "kΩ")


if __name__ == "__main__":
    unittest.main()
