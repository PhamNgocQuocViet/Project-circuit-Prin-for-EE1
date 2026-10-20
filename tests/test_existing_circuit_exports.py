import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from circuit_engine.io.circuit_importer import reconstruct_circuit_from_dict
from circuit_engine.io.circuit_serializer import serialize_circuit
from ui.canvas import CircuitCanvas


class ExistingCircuitExportCompatibilityTests(unittest.TestCase):
    """Protect the bundled pre-schematic export format from regressions."""

    EXPORT_DIRECTORY = Path(__file__).resolve().parents[1] / "circuit_exports"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_existing_exports_load_and_round_trip(self):
        export_paths = sorted(self.EXPORT_DIRECTORY.glob("*.circuit"))
        self.assertTrue(export_paths, "No existing circuit exports were found")

        for export_path in export_paths:
            with self.subTest(export=export_path.name):
                with export_path.open(encoding="utf-8") as export_file:
                    original = json.load(export_file)

                canvas = CircuitCanvas()
                references = reconstruct_circuit_from_dict(original, canvas)

                self.assertEqual(len(canvas.components), len(original.get("components", [])))
                self.assertEqual(len(canvas.connection_lines), len(original.get("connections", [])))
                self.assertEqual(len(references), len(original.get("components", [])))

                round_trip = serialize_circuit(
                    canvas.components,
                    original.get("circuit_name", "Untitled Circuit"),
                    canvas.connection_lines,
                )
                original_by_id = {item["id"]: item for item in original.get("components", [])}
                round_trip_by_id = {item["id"]: item for item in round_trip["components"]}
                self.assertEqual(set(round_trip_by_id), set(original_by_id))

                for component_id, original_component in original_by_id.items():
                    restored = round_trip_by_id[component_id]
                    for field in ("type", "grid_x", "grid_y", "rotation", "assigned_value"):
                        self.assertEqual(restored[field], original_component.get(field, ""))

                original_connections = {
                    (item["from"], item.get("from_terminal", "positive"),
                     item["to"], item.get("to_terminal", "negative"))
                    for item in original.get("connections", [])
                }
                restored_connections = {
                    (item["from"], item["from_terminal"], item["to"], item["to_terminal"])
                    for item in round_trip["connections"]
                }
                self.assertEqual(restored_connections, original_connections)

                # Old rotations must not reintroduce vertical reference text.
                for component in canvas.components:
                    label_origin = component.label.mapToScene(0, 0)
                    label_x_axis = component.label.mapToScene(1, 0)
                    self.assertAlmostEqual(label_origin.y(), label_x_axis.y(), places=5)


if __name__ == "__main__":
    unittest.main()
