"""Interactive graphics canvas for placing, wiring, moving, and removing parts.

The canvas translates mouse, keyboard, wheel, and drag/drop input into changes
to graphics items. It also records enough action history to support the UI's
single-step undo behavior.
"""

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QPen, QColor, QBrush, QPainter, QPixmap

from components.component_factory import ComponentFactory
from components.electrical_component import ComponentType

class CircuitCanvas(QGraphicsView):
    """Grid-based editor for component placement and terminal-aware wiring."""

    component_added = pyqtSignal(object)
    component_removed = pyqtSignal(object)
    canvas_cleared = pyqtSignal()
    circuit_changed = pyqtSignal()

    GRID_SIZE = 40
    COMPONENT_MIME_TYPE = "application/x-ee-component"
    WIRE_WIDTH = 3
    GRID_LINE_COLOR = QColor(220, 220, 220)
    GRID_BACKGROUND_COLOR = QColor(255, 255, 255)
    WIRE_COLOR = QColor(100, 100, 100)
    NODE_LABEL_COLOR = QColor(32, 33, 36)
    MAX_SCENE_EXTENT = 100000
    FIT_MARGIN = 120
    ZOOM_IN_FACTOR = 1.15
    MIN_ZOOM = 0.2
    MAX_ZOOM = 5.0
    DRAG_SELECTION_COLOR = QColor(100, 150, 255)
    CONNECTION_SELECTION_COLOR = QColor(100, 200, 100)
    
    def __init__(self, parent=None):
        """Create the scene and initialize interaction history and state.

        Args:
            parent: Optional widget that owns this graphics view.
        """
        super().__init__(parent)
        
        # Create scene
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        # Setup canvas
        self.scene.setBackgroundBrush(self.create_grid_brush())
        self.setRenderHint(QPainter.Antialiasing)
        self.setFocusPolicy(Qt.StrongFocus)  # Allow keyboard input
        
        # Large virtual scene with dynamic grid drawing keeps memory usage low.
        max_extent = self.MAX_SCENE_EXTENT
        self.scene.setSceneRect(-max_extent, -max_extent, max_extent * 2, max_extent * 2)
        
        # Components
        self.components = []
        self.connection_lines = []
        self.selected_component_type = None
        self.action_history = []
        
        # Connection mode
        self.connection_mode = False
        self.first_component = None
        self.selected_component = None
        
        # Drag and drop
        self.setAcceptDrops(True)
        self._middle_panning = False
        self._pan_last_pos = QPoint()

    def apply_theme(self, resolved_theme):
        """Update canvas-only colors that live outside QApplication QSS."""
        if resolved_theme == "dark":
            self.GRID_BACKGROUND_COLOR = QColor(21, 25, 30)
            self.GRID_LINE_COLOR = QColor(47, 55, 64)
            self.WIRE_COLOR = QColor(186, 198, 210)
            self.NODE_LABEL_COLOR = QColor(232, 237, 242)
        else:
            self.GRID_BACKGROUND_COLOR = QColor(255, 255, 255)
            self.GRID_LINE_COLOR = QColor(220, 220, 220)
            self.WIRE_COLOR = QColor(100, 100, 100)
            self.NODE_LABEL_COLOR = QColor(32, 33, 36)

        self.scene.setBackgroundBrush(self.create_grid_brush())
        for line in self.connection_lines:
            pen = QPen(self.WIRE_COLOR, self.WIRE_WIDTH)
            pen.setCosmetic(True)
            line.setPen(pen)
        for component in self.components:
            self._apply_component_theme(component)
        self.scene.update()
        self.viewport().update()

    def _apply_component_theme(self, component):
        """Apply canvas theme colors to graphics items owned by the canvas."""
        if hasattr(component, "set_schematic_theme"):
            component.set_schematic_theme(self.GRID_BACKGROUND_COLOR.lightness() < 128)

    def refresh_component_labels(self):
        """Reposition all labels after placement, movement, or bulk loading."""
        for component in self.components:
            if hasattr(component, "update_label_position"):
                component.update_label_position(self.components)

    def create_grid_brush(self):
        """Create a lightweight repeating grid brush for an effectively infinite canvas."""
        tile = QPixmap(self.GRID_SIZE, self.GRID_SIZE)
        tile.fill(self.GRID_BACKGROUND_COLOR)

        painter = QPainter(tile)
        painter.setPen(QPen(self.GRID_LINE_COLOR, 1))
        painter.drawLine(0, 0, self.GRID_SIZE, 0)
        painter.drawLine(0, 0, 0, self.GRID_SIZE)
        painter.end()

        return QBrush(tile)
    
    def set_selected_component(self, comp_type):
        """Set the component type to add when clicking"""
        self.selected_component_type = comp_type

    def place_component(self, comp_type, scene_pos):
        """Create and place a component at the nearest grid point."""
        grid_x = round(scene_pos.x() / self.GRID_SIZE)
        grid_y = round(scene_pos.y() / self.GRID_SIZE)

        component = ComponentFactory.create_component(comp_type, grid_x, grid_y)
        self._apply_component_theme(component)
        self.scene.addItem(component)
        self.components.append(component)
        self.refresh_component_labels()
        self.action_history.append({
            "action": "add_component",
            "component": component,
        })
        self.component_added.emit(component)
        self.circuit_changed.emit()
        return component

    def component_type_from_mime(self, mime_data):
        """Parse a ComponentType from drag mime data."""
        if mime_data.hasFormat(self.COMPONENT_MIME_TYPE):
            raw_type_name = bytes(mime_data.data(self.COMPONENT_MIME_TYPE)).decode("utf-8")
            if raw_type_name in ComponentType.__members__:
                return ComponentType[raw_type_name]

        if mime_data.hasText():
            for comp_type in ComponentType:
                if comp_type.value == mime_data.text():
                    return comp_type

        return None

    def find_component_at(self, view_pos):
        """Return the component located at a viewport position, if any."""
        clicked_item = self.itemAt(view_pos)
        for comp in self.components:
            if clicked_item == comp or (hasattr(clicked_item, 'parentItem') and clicked_item.parentItem() == comp):
                return comp
        return None

    def clear_active_highlights(self):
        """Clear drag and connection highlights from active components."""
        highlighted_components = []
        if self.selected_component is not None:
            highlighted_components.append(self.selected_component)
        if self.first_component is not None and self.first_component not in highlighted_components:
            highlighted_components.append(self.first_component)

        for component in highlighted_components:
            component.set_persistent_highlight()

        self.selected_component = None
        self.first_component = None
        self.connection_mode = False

    def set_drag_selected_component(self, component):
        """Keep a component highlighted as the active drag-selected item."""
        if self.selected_component and self.selected_component != component and self.selected_component != self.first_component:
            self.selected_component.set_persistent_highlight()

        self.selected_component = component
        if component is not None and component != self.first_component:
            component.set_persistent_highlight(self.DRAG_SELECTION_COLOR)
    
    def mousePressEvent(self, event):
        """Handle mouse click on canvas"""
        if event.button() == Qt.MiddleButton:
            self._middle_panning = True
            self._pan_last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        pos = self.mapToScene(event.pos())
        
        component = self.find_component_at(event.pos())

        # Right-click: Handle connection
        if event.button() == Qt.RightButton:
            if component is None:
                self.clear_active_highlights()
                event.accept()
                return

            if not self.connection_mode:
                if self.selected_component and self.selected_component != component and self.selected_component != self.first_component:
                    self.selected_component.set_persistent_highlight()
                self.selected_component = component
                self.connection_mode = True
                self.first_component = component
                component.set_persistent_highlight(self.CONNECTION_SELECTION_COLOR)
            else:
                second_component = component
                if second_component != self.first_component:
                    self.connect_components(self.first_component, second_component)

                # Exit connection mode and keep the second component selected for drag
                if self.first_component is not None:
                    self.first_component.set_persistent_highlight()
                self.connection_mode = False
                self.first_component = None
                self.set_drag_selected_component(second_component)

            event.accept()
            return
        
        # Left-click: Place component or allow drag
        if event.button() == Qt.LeftButton:
            if self.selected_component_type is not None:
                self.clear_active_highlights()
                placed_component = self.place_component(self.selected_component_type, pos)
                self.set_drag_selected_component(placed_component)
                
                # Deselect component type
                self.selected_component_type = None
                event.accept()
                return

            if component is not None:
                self.set_drag_selected_component(component)
            else:
                self.clear_active_highlights()
        
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        """Accept drags that carry a component type."""
        if self.component_type_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return

        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Continue accepting valid component drags while moving."""
        if self.component_type_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return

        super().dragMoveEvent(event)

    def dropEvent(self, event):
        """Drop a component from the component list onto the grid."""
        comp_type = self.component_type_from_mime(event.mimeData())
        if comp_type is None:
            super().dropEvent(event)
            return

        scene_pos = self.mapToScene(event.pos())
        self.place_component(comp_type, scene_pos)
        event.acceptProposedAction()

    def mouseMoveEvent(self, event):
        """Support middle-button panning across the expanded canvas."""
        if self._middle_panning:
            delta = event.pos() - self._pan_last_pos
            self._pan_last_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Finish middle-button panning."""
        if event.button() == Qt.MiddleButton and self._middle_panning:
            self._middle_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """Zoom with mouse wheel and block wheel-based canvas scrolling."""
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            event.accept()
            return

        zoom_factor = self.ZOOM_IN_FACTOR if delta_y > 0 else 1.0 / self.ZOOM_IN_FACTOR
        current_zoom = self.transform().m11()
        new_zoom = current_zoom * zoom_factor
        if new_zoom < self.MIN_ZOOM or new_zoom > self.MAX_ZOOM:
            event.accept()
            return

        previous_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(zoom_factor, zoom_factor)
        self.setTransformationAnchor(previous_anchor)
        event.accept()

    def keyPressEvent(self, event):
        """Handle keyboard events"""
        if event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
            self.undo_last_action()
            event.accept()
            return

        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_component:
            self.delete_selected_component()
            event.accept()
            return

        if event.key() == Qt.Key_R and self.selected_component:
            # Rotate selected component
            self.selected_component.rotate()
            event.accept()
            return
        
        super().keyPressEvent(event)

    def back_to_center_view(self):
        """Fit the view around all placed components and wires."""
        if not self.components and not self.connection_lines:
            self.resetTransform()
            self.centerOn(0, 0)
            return

        target_rect = self.scene.itemsBoundingRect().adjusted(
            -self.FIT_MARGIN, -self.FIT_MARGIN, self.FIT_MARGIN, self.FIT_MARGIN
        )
        self.fitInView(target_rect, Qt.KeepAspectRatio)
    
    def connect_components(self, comp1, comp2):
        """
        Connect two components with a wire
        
        Args:
            comp1: First component
            comp2: Second component
        """
        # Check if already connected
        if comp2 in comp1.connections:
            return
        
        comp1.connect_to(comp2)
        comp2.connect_to(comp1)
        self.draw_connection_line(comp1, comp2)
        self.action_history.append({
            "action": "connect_components",
            "comp1": comp1,
            "comp2": comp2,
        })
        self.circuit_changed.emit()

    def remove_connection_between(self, comp1, comp2):
        """Remove a direct connection wire between two components."""
        wire_to_remove = None
        for wire in self.connection_lines:
            same_direction = wire.source == comp1 and wire.target == comp2
            reverse_direction = wire.source == comp2 and wire.target == comp1
            if same_direction or reverse_direction:
                wire_to_remove = wire
                break

        if wire_to_remove is not None:
            if wire_to_remove in comp1.connected_wires:
                comp1.connected_wires.remove(wire_to_remove)
            if wire_to_remove in comp2.connected_wires:
                comp2.connected_wires.remove(wire_to_remove)
            if wire_to_remove in self.connection_lines:
                self.connection_lines.remove(wire_to_remove)
            self.scene.removeItem(wire_to_remove)

        if comp2 in comp1.connections:
            comp1.connections.remove(comp2)
        if comp1 in comp2.connections:
            comp2.connections.remove(comp1)

    def remove_component(self, component):
        """Remove a component and all of its connected wires."""
        if component is None:
            return

        for wire in list(component.connected_wires):
            if wire in self.connection_lines:
                self.connection_lines.remove(wire)

            other_component = wire.target if wire.source == component else wire.source
            if hasattr(other_component, "connected_wires") and wire in other_component.connected_wires:
                other_component.connected_wires.remove(wire)
            if hasattr(other_component, "connections") and component in other_component.connections:
                other_component.connections.remove(component)

            self.scene.removeItem(wire)

        component.connected_wires.clear()

        for other_component in list(component.connections):
            if hasattr(other_component, "connections") and component in other_component.connections:
                other_component.connections.remove(component)
        component.connections.clear()

        if component in self.components:
            self.components.remove(component)
        self.scene.removeItem(component)
        self.refresh_component_labels()

        if self.first_component == component:
            self.first_component = None
            self.connection_mode = False

        component.set_persistent_highlight()
        if self.selected_component == component:
            self.selected_component = None
        self.component_removed.emit(component)
        self.circuit_changed.emit()

    def undo_last_action(self):
        """Undo the most recent add-component or connect-components action."""
        if not self.action_history:
            return

        action = self.action_history.pop()
        action_type = action.get("action")

        if action_type == "add_component":
            component = action.get("component")
            if component in self.components:
                self.remove_component(component)
            return

        if action_type == "connect_components":
            comp1 = action.get("comp1")
            comp2 = action.get("comp2")
            if comp1 in self.components and comp2 in self.components:
                self.remove_connection_between(comp1, comp2)
                self.circuit_changed.emit()
            return
    
    def draw_connection_line(self, comp1, comp2):
        """Draw a visual connection line between two components"""
        # Get terminal positions
        pos_term1, neg_term1 = comp1.get_terminal_pos()
        pos_term2, neg_term2 = comp2.get_terminal_pos()
        
        # Connect positive of comp1 to negative of comp2 (current flow)
        x1 = pos_term1[0]
        y1 = pos_term1[1]
        x2 = neg_term2[0]
        y2 = neg_term2[1]
        
        # Create line
        wire_pen = QPen(self.WIRE_COLOR, self.WIRE_WIDTH)
        wire_pen.setCosmetic(True)
        line = self.scene.addLine(x1, y1, x2, y2, wire_pen)
        line.source = comp1
        line.target = comp2
        
        # Store wire references in components for updating
        comp1.connected_wires.append(line)
        comp2.connected_wires.append(line)
        
        self.connection_lines.append(line)
    
    def clear_all(self):
        """Clear all components and connections from canvas"""
        self.clear_active_highlights()

        # Remove all components
        for component in self.components:
            self.scene.removeItem(component)
        self.components.clear()
        
        # Remove all connection lines
        for line in self.connection_lines:
            self.scene.removeItem(line)
        self.connection_lines.clear()
        self.action_history.clear()
        self.resetTransform()
        self.centerOn(0, 0)
        self.canvas_cleared.emit()
        self.circuit_changed.emit()

    def delete_selected_component(self):
        """Remove the currently selected component and any wires connected to it"""
        component = self.selected_component
        self.remove_component(component)
