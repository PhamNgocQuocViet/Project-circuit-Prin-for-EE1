import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

from components.electrical_component import ComponentType, ElectricalComponent
from ui.canvas import CircuitCanvas


class ComponentSchematicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = CircuitCanvas()

    def _add(self, component_type, grid_x=0, grid_y=0, name="R#1"):
        component = ElectricalComponent(component_type, grid_x, grid_y)
        self.canvas.scene.addItem(component)
        self.canvas.components.append(component)
        component.update_label_text(name)
        self.canvas.refresh_component_labels()
        return component

    def test_rotated_terminals_remain_aligned_and_label_stays_horizontal(self):
        component = self._add(ComponentType.RESISTOR)
        component.rotate()

        positive, negative = component.get_terminal_pos()
        self.assertAlmostEqual(positive[0], negative[0], places=5)
        self.assertGreater(abs(positive[1] - negative[1]), 45)

        label_origin = component.label.mapToScene(0, 0)
        label_x_axis = component.label.mapToScene(1, 0)
        self.assertAlmostEqual(label_origin.y(), label_x_axis.y(), places=5)

    def test_vertical_label_chooses_clear_side(self):
        component = self._add(ComponentType.CAPACITOR, 0, 0, "C#1")
        component.rotate()
        blocker = self._add(ComponentType.RESISTOR, 1, 0, "R#1")
        blocker.rotate()
        self.canvas.refresh_component_labels()

        self.assertLess(component.label.sceneBoundingRect().right(),
                        component._component_body_scene_rect().left())

    def test_dark_theme_uses_light_symbol_and_negative_terminal(self):
        component = self._add(ComponentType.VOLTAGE_SOURCE)
        component.set_schematic_theme(True)

        self.assertGreater(component.symbol_color.lightness(), 128)
        self.assertGreater(component.terminal_neg.brush().color().lightness(), 128)
        self.assertEqual(component.label.defaultTextColor(), component.symbol_color)

    def test_light_theme_uses_dark_symbol(self):
        component = self._add(ComponentType.INDUCTOR)
        component.set_schematic_theme(False)

        self.assertLess(component.symbol_color.lightness(), 128)
        self.assertEqual(component.symbol_color, QColor(component.LIGHT_SYMBOL_COLOR))

    def test_node_has_larger_invisible_hit_area_without_moving_terminal(self):
        node = self._add(ComponentType.NODE, 2, 3, "Node A")

        self.assertEqual(node.rect().width(), node.NODE_HIT_SIZE)
        self.assertEqual(node.rect().height(), node.NODE_HIT_SIZE)
        self.assertTrue(node.shape().contains(QPointF(1, node.NODE_HIT_SIZE / 2)))

        positive, negative = node.get_terminal_pos()
        expected_center = (2 * node.GRID_SIZE, 3 * node.GRID_SIZE)
        self.assertEqual(positive, expected_center)
        self.assertEqual(negative, expected_center)
        self.assertEqual(node._component_body_scene_rect().width(), node.NODE_VISUAL_SIZE)

    @staticmethod
    def _distance(point, terminal):
        return ((point.x() - terminal[0]) ** 2 + (point.y() - terminal[1]) ** 2) ** 0.5

    def test_current_arrow_points_from_white_to_red_at_every_rotation(self):
        component = self._add(ComponentType.CURRENT_SOURCE, name="I#1")

        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                component.rotation_angle = rotation
                component.setRotation(rotation)
                tail, tip, _upper_wing, _lower_wing = component._current_arrow_points()
                tail = component.mapToScene(tail)
                tip = component.mapToScene(tip)
                positive, negative = component.get_terminal_pos()
                self.assertLess(self._distance(tip, positive), self._distance(tip, negative))
                self.assertLess(self._distance(tail, negative), self._distance(tail, positive))

    def test_voltage_polarity_stays_nearest_matching_terminal(self):
        component = self._add(ComponentType.VOLTAGE_SOURCE, name="V#1")

        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                component.rotation_angle = rotation
                component.setRotation(rotation)
                plus, minus = component._voltage_polarity_positions()
                plus = component.mapToScene(plus)
                minus = component.mapToScene(minus)
                positive, negative = component.get_terminal_pos()
                self.assertLess(self._distance(plus, positive), self._distance(plus, negative))
                self.assertLess(self._distance(minus, negative), self._distance(minus, positive))


if __name__ == "__main__":
    unittest.main()
