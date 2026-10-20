"""Graphics model shared by all electrical component types.

ElectricalComponent stores display position, terminal geometry, value/unit
metadata, and wire relationships while providing Qt interaction hooks for
selection, rotation, snapping, and movement.
"""

from enum import Enum
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QColor, QFont, QBrush, QPainterPath
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsTextItem, QGraphicsEllipseItem, QGraphicsItem

class ComponentType(Enum):
    """Component categories understood by the palette and circuit engine."""
    RESISTOR = "Resistor"
    CAPACITOR = "Capacitor"
    INDUCTOR = "Inductor"
    VOLTAGE_SOURCE = "Voltage Source"
    CURRENT_SOURCE = "Current Source"
    NODE = "Node"

class ElectricalComponent(QGraphicsRectItem):
    """Interactive circuit component rendered with a standard schematic symbol."""
    
    GRID_SIZE = 40  # Less dense grid (larger cell size)
    COMPONENT_WIDTH = 50  # Default horizontal width
    COMPONENT_HEIGHT = 25  # Default horizontal height
    NODE_VISUAL_SIZE = 12
    NODE_HIT_SIZE = 28
    DEFAULT_BRUSH_COLOR = QColor(200, 220, 255)
    HOVER_BRUSH_COLOR = QColor(150, 180, 255)
    SELECTED_BRUSH_COLOR = QColor(100, 150, 255)
    NODE_DEFAULT_BRUSH_COLOR = QColor(14, 55, 102)
    NODE_HOVER_BRUSH_COLOR = QColor(24, 75, 130)
    NODE_SELECTED_BRUSH_COLOR = QColor(32, 96, 158)
    LIGHT_SYMBOL_COLOR = QColor(24, 27, 31)
    DARK_SYMBOL_COLOR = QColor(235, 240, 245)
    LABEL_GAP = 5.0
    LABELS = {
        ComponentType.RESISTOR: "R",
        ComponentType.CAPACITOR: "C",
        ComponentType.INDUCTOR: "L",
        ComponentType.VOLTAGE_SOURCE: "V",
        ComponentType.CURRENT_SOURCE: "I",
        ComponentType.NODE: "",
    }
    
    def __init__(self, comp_type, x, y):
        """
        Initialize an electrical component
        
        Args:
            comp_type: ComponentType enum value
            x: Grid x position
            y: Grid y position
        """
        width = self.COMPONENT_WIDTH
        height = self.COMPONENT_HEIGHT
        if comp_type == ComponentType.NODE:
            # Give the small node dot a forgiving click target without making
            # its visible schematic symbol or wire connection point larger.
            width = self.NODE_HIT_SIZE
            height = self.NODE_HIT_SIZE
        super().__init__(0, 0, width, height)
        
        self.comp_type = comp_type
        self.grid_x = x
        self.grid_y = y
        self.rotation_angle = 0  # 0, 90, 180, 270 degrees
        
        # Store connections and wires (initialize early before any events)
        self.connections = []
        self.connected_wires = []  # Store wire line references
        self.is_selected = False
        self.is_hovered = False
        self.persistent_highlight_color = None
        self.default_brush_color = self.NODE_DEFAULT_BRUSH_COLOR if comp_type == ComponentType.NODE else self.DEFAULT_BRUSH_COLOR
        self.hover_brush_color = self.NODE_HOVER_BRUSH_COLOR if comp_type == ComponentType.NODE else self.HOVER_BRUSH_COLOR
        self.selected_brush_color = self.NODE_SELECTED_BRUSH_COLOR if comp_type == ComponentType.NODE else self.SELECTED_BRUSH_COLOR
        self.symbol_color = QColor(self.LIGHT_SYMBOL_COLOR)
        
        # Visual properties
        self.setPen(QPen(self.symbol_color, 2))
        # The inherited rectangle supplies a stable hit area, but paint() draws
        # only the electrical symbol (plus a selection halo when appropriate).
        self.setBrush(QBrush(Qt.NoBrush))
        self.setAcceptHoverEvents(True)
        
        # Make draggable
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setTransformOriginPoint(width / 2, height / 2)
        
        # Set position on canvas (centered on grid line)
        pixel_x = x * self.GRID_SIZE
        pixel_y = y * self.GRID_SIZE
        self.setPos(pixel_x - width / 2, pixel_y - height / 2)
        
        # Label
        self.label = QGraphicsTextItem("", self)
        # Keep text above terminal markers and schematic strokes even when its
        # collision-aware position extends beyond the component hit box.
        self.label.setZValue(2)
        label_font = QFont()
        label_font.setPointSize(7)
        label_font.setBold(True)
        self.label.setFont(label_font)
        self.label.setDefaultTextColor(self.symbol_color)
        if comp_type == ComponentType.NODE:
            # Node components are drawn as a tiny dot; the name (e.g. "Node A")
            # is set later by the UI once the reference name is assigned, and
            # rendered above the dot instead of centered inside it.
            self.label.setDefaultTextColor(self.symbol_color)
        self.update_label_text(self.LABELS.get(comp_type, comp_type.value[0]))
        
        # Add terminal indicators - positioned where wires connect
        terminal_size = 8
        if comp_type == ComponentType.NODE:
            self.setBrush(self.default_brush_color)
            self.setPen(QPen(QColor(8, 35, 70), 1))

            center_x = width / 2 - terminal_size / 2
            center_y = height / 2 - terminal_size / 2
            self.terminal_pos = QGraphicsEllipseItem(center_x, center_y, terminal_size, terminal_size, self)
            self.terminal_pos.setBrush(QBrush(QColor(8, 35, 70)))
            self.terminal_pos.setPen(QPen(QColor(8, 35, 70), 1))

            self.terminal_neg = QGraphicsEllipseItem(center_x, center_y, terminal_size, terminal_size, self)
            self.terminal_neg.setBrush(QBrush(QColor(8, 35, 70)))
            self.terminal_neg.setPen(QPen(QColor(8, 35, 70), 1))
        else:
            # Terminals positioned at left/right edges in default horizontal orientation
            self.terminal_pos = QGraphicsEllipseItem(-terminal_size / 2,
                                                     height / 2 - terminal_size / 2, terminal_size, terminal_size, self)
            self.terminal_pos.setBrush(QBrush(QColor(255, 0, 0)))  # Red for positive
            self.terminal_pos.setPen(QPen(QColor(200, 0, 0), 2))

            self.terminal_neg = QGraphicsEllipseItem(width - terminal_size / 2,
                                                     height / 2 - terminal_size / 2, terminal_size, terminal_size, self)
            self.terminal_neg.setBrush(QBrush(QColor(0, 0, 0)))  # Black for negative/ground
            self.terminal_neg.setPen(QPen(QColor(50, 50, 50), 2))

    def paint(self, painter, option, widget=None):
        """Paint the component as an IEC-style vector schematic symbol."""
        if self.comp_type == ComponentType.NODE:
            # The child terminal dot is the normal node visual; a circular halo
            # preserves the same hover/selection feedback as other symbols.
            highlight = self.persistent_highlight_color
            if highlight is None and self.is_selected:
                highlight = self.selected_brush_color
            if highlight is None and self.is_hovered:
                highlight = self.hover_brush_color
            if highlight is not None:
                halo = QColor(highlight)
                halo.setAlpha(120)
                painter.setPen(QPen(halo, 4))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(self._node_visual_rect().adjusted(1, 1, -1, -1))
            return

        painter.setRenderHint(painter.Antialiasing, True)
        pen = QPen(self.symbol_color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Highlight with a soft, non-rectangular halo so the symbol never falls
        # back to looking like the old rectangular component.
        highlight = self.persistent_highlight_color
        if highlight is None and self.is_selected:
            highlight = self.selected_brush_color
        if highlight is None and self.is_hovered:
            highlight = self.hover_brush_color
        if highlight is not None:
            halo = QColor(highlight)
            halo.setAlpha(90)
            painter.setPen(QPen(halo, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(QPointF(4, self.COMPONENT_HEIGHT / 2),
                             QPointF(self.COMPONENT_WIDTH - 4, self.COMPONENT_HEIGHT / 2))
            painter.setPen(pen)

        mid_y = self.COMPONENT_HEIGHT / 2
        if self.comp_type == ComponentType.RESISTOR:
            path = QPainterPath(QPointF(0, mid_y))
            path.lineTo(8, mid_y)
            for point in ((12, 6), (17, 19), (22, 6), (27, 19), (32, 6), (37, 19), (42, mid_y)):
                path.lineTo(*point)
            path.lineTo(self.COMPONENT_WIDTH, mid_y)
            painter.drawPath(path)
        elif self.comp_type == ComponentType.CAPACITOR:
            painter.drawLine(QPointF(0, mid_y), QPointF(21, mid_y))
            painter.drawLine(QPointF(21, 4), QPointF(21, 21))
            painter.drawLine(QPointF(29, 4), QPointF(29, 21))
            painter.drawLine(QPointF(29, mid_y), QPointF(self.COMPONENT_WIDTH, mid_y))
        elif self.comp_type == ComponentType.INDUCTOR:
            path = QPainterPath(QPointF(0, mid_y))
            path.lineTo(7, mid_y)
            for left in (7, 16, 25, 34):
                path.cubicTo(left, 4, left + 9, 4, left + 9, mid_y)
            path.lineTo(self.COMPONENT_WIDTH, mid_y)
            painter.drawPath(path)
        elif self.comp_type in (ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE):
            painter.drawLine(QPointF(0, mid_y), QPointF(15, mid_y))
            painter.drawEllipse(QPointF(25, mid_y), 10, 10)
            painter.drawLine(QPointF(35, mid_y), QPointF(self.COMPONENT_WIDTH, mid_y))
            if self.comp_type == ComponentType.VOLTAGE_SOURCE:
                positive, negative = self._voltage_polarity_positions()
                painter.drawLine(positive + QPointF(0, -2.5), positive + QPointF(0, 2.5))
                painter.drawLine(positive + QPointF(-2.5, 0), positive + QPointF(2.5, 0))
                painter.drawLine(negative + QPointF(-2.5, 0), negative + QPointF(2.5, 0))
            else:
                tail, tip, upper_wing, lower_wing = self._current_arrow_points()
                painter.drawLine(tail, tip)
                painter.drawLine(tip, upper_wing)
                painter.drawLine(tip, lower_wing)

    def _voltage_polarity_positions(self):
        """Return local +/− centers, each anchored toward its matching terminal."""
        mid_y = self.COMPONENT_HEIGHT / 2
        return QPointF(20, mid_y), QPointF(30, mid_y)

    def _current_arrow_points(self):
        """Return an arrow pointing from the negative terminal toward positive."""
        mid_y = self.COMPONENT_HEIGHT / 2
        # Default orientation has positive/red on the left and negative/white
        # on the right. Because these points belong to the component item, the
        # complete arrow rotates with both terminals when R is pressed.
        return (
            QPointF(31, mid_y),
            QPointF(19, mid_y),
            QPointF(24, mid_y - 4),
            QPointF(24, mid_y + 4),
        )

    def update_label_text(self, text):
        """Set the reference text and keep it horizontal beside the symbol."""
        self.label.setScale(1.0)
        self.label.setPlainText(text)
        self._refresh_scene_labels()

    def set_schematic_theme(self, dark_mode=False):
        """Set symbol, label, and negative-terminal colors for the canvas theme."""
        self.symbol_color = QColor(self.DARK_SYMBOL_COLOR if dark_mode else self.LIGHT_SYMBOL_COLOR)
        self.setPen(QPen(self.symbol_color, 2))
        self.label.setDefaultTextColor(self.symbol_color)
        if self.comp_type == ComponentType.NODE:
            dot = QColor(87, 166, 255) if dark_mode else QColor(14, 55, 102)
            self.setPen(QPen(dot, 1))
            self.terminal_pos.setBrush(QBrush(dot))
            self.terminal_pos.setPen(QPen(dot, 1))
            self.terminal_neg.setBrush(QBrush(dot))
            self.terminal_neg.setPen(QPen(dot, 1))
        else:
            negative = QColor(235, 240, 245) if dark_mode else QColor(20, 20, 20)
            self.terminal_neg.setBrush(QBrush(negative))
            self.terminal_neg.setPen(QPen(negative.darker(115), 2))
        self.update()

    def _component_body_scene_rect(self):
        """Return the symbol hit-box in scene coordinates, excluding its label."""
        if self.comp_type == ComponentType.NODE:
            # Label collision detection follows the visible dot rather than
            # the deliberately larger invisible node click target.
            return self.mapRectToScene(self._node_visual_rect())
        return self.mapRectToScene(self.rect())

    def _node_visual_rect(self):
        """Return the centered visible bounds of a node inside its hit area."""
        inset_x = (self.rect().width() - self.NODE_VISUAL_SIZE) / 2
        inset_y = (self.rect().height() - self.NODE_VISUAL_SIZE) / 2
        return QRectF(inset_x, inset_y, self.NODE_VISUAL_SIZE, self.NODE_VISUAL_SIZE)

    @staticmethod
    def _overlap_score(candidate, other_components):
        """Score label obstruction; component bodies are costlier than labels."""
        score = 0.0
        for other in other_components:
            body = other._component_body_scene_rect().adjusted(-2, -2, 2, 2)
            body_overlap = candidate.intersected(body)
            score += body_overlap.width() * body_overlap.height() * 8.0
            other_label = getattr(other, "label", None)
            if other_label is not None and other_label.isVisible():
                label_overlap = candidate.intersected(other_label.sceneBoundingRect())
                score += label_overlap.width() * label_overlap.height() * 4.0
        return score

    def update_label_position(self, components=None):
        """Keep the label horizontal and choose the least-obstructed nearby side."""
        if not hasattr(self, "label"):
            return

        # Cancel the parent's component rotation so text always reads normally.
        self.label.setTransformOriginPoint(0, 0)
        self.label.setRotation(-self.rotation_angle)
        text_rect = self.label.boundingRect()
        width, height = text_rect.width(), text_rect.height()
        body = self._component_body_scene_rect()
        gap = self.LABEL_GAP

        if self.comp_type != ComponentType.NODE and self.rotation_angle % 180 == 90:
            candidates = [
                QRectF(body.left() - gap - width, body.center().y() - height / 2, width, height),
                QRectF(body.right() + gap, body.center().y() - height / 2, width, height),
            ]
        else:
            candidates = [
                QRectF(body.center().x() - width / 2, body.bottom() + gap, width, height),
                QRectF(body.center().x() - width / 2, body.top() - gap - height, width, height),
            ]

        if components is None:
            scene = self.scene()
            components = [item for item in scene.items() if isinstance(item, ElectricalComponent)] if scene else []
        others = [component for component in components if component is not self]
        best = min(candidates, key=lambda candidate: self._overlap_score(candidate, others))

        # mapFromScene accounts for the parent's rotation; the inverse child
        # rotation then leaves the label's glyphs horizontal in scene space.
        local_top_left = self.mapFromScene(best.topLeft())
        self.label.setPos(local_top_left)

    def _refresh_scene_labels(self):
        """Re-evaluate nearby labels after this component moves or rotates."""
        scene = self.scene()
        if scene is None:
            self.update_label_position()
            return
        components = [item for item in scene.items() if isinstance(item, ElectricalComponent)]
        for component in components:
            component.update_label_position(components)

    def set_persistent_highlight(self, color=None):
        """Keep a schematic symbol highlighted until explicitly cleared."""
        self.persistent_highlight_color = QColor(color) if color is not None else None
        if self.persistent_highlight_color is not None:
            self.update()
        elif not self.is_selected:
            self.update()
    
    def snap_to_grid(self, pixel_x, pixel_y):
        """
        Snap component to nearest grid position
        
        Args:
            pixel_x: X position in pixels
            pixel_y: Y position in pixels
        """
        # Find nearest grid position (allow snapping within ~1.5 cells)
        grid_x = round(pixel_x / self.GRID_SIZE)
        grid_y = round(pixel_y / self.GRID_SIZE)
        
        # Update grid position (allow negative coordinates for expanded canvas)
        self.grid_x = grid_x
        self.grid_y = grid_y
        
        # Move to snapped position (centered on grid line)
        pixel_x = self.grid_x * self.GRID_SIZE
        pixel_y = self.grid_y * self.GRID_SIZE
        rect = self.rect()
        self.setPos(pixel_x - rect.width() / 2, pixel_y - rect.height() / 2)
    
    def get_terminal_pos(self):
        """
        Get the position of positive and negative terminals based on rotation
        
        Returns:
            Tuple of (pos_terminal_pos, neg_terminal_pos) as (x, y) tuples
        """
        pos_center = self.terminal_pos.mapToScene(self.terminal_pos.boundingRect().center())
        neg_center = self.terminal_neg.mapToScene(self.terminal_neg.boundingRect().center())
        return ((pos_center.x(), pos_center.y()), (neg_center.x(), neg_center.y()))
    
    def rotate(self):
        """Rotate component 90 degrees clockwise"""
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.setRotation(self.rotation_angle)
        self._refresh_scene_labels()
        # Update all connected wires after rotation
        self.update_connected_wires()
    
    def connect_to(self, other_component):
        """Connect this component to another"""
        if other_component not in self.connections:
            self.connections.append(other_component)
    
    def disconnect_from(self, other_component):
        """Disconnect from another component"""
        if other_component in self.connections:
            self.connections.remove(other_component)
    
    def mousePressEvent(self, event):
        """Handle mouse press for selection"""
        self.is_selected = True
        if self.persistent_highlight_color is None:
            self.update()
        super().mousePressEvent(event)
    
    def hoverEnterEvent(self, event):
        """Handle hover enter"""
        if not self.is_selected and self.persistent_highlight_color is None:
            self.is_hovered = True
            self.update()
    
    def hoverLeaveEvent(self, event):
        """Handle hover leave"""
        if self.is_hovered:
            self.is_hovered = False
            self.update()
    
    def itemChange(self, change, value):
        """Handle item change events (for drag updates)"""
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Update grid position after the item has moved so wire endpoints use the new terminal locations
            current_center = self.mapToScene(self.boundingRect().center())
            self.grid_x = round(current_center.x() / self.GRID_SIZE)
            self.grid_y = round(current_center.y() / self.GRID_SIZE)

            # Update all connected wires
            if hasattr(self, 'connected_wires'):
                self.update_connected_wires()
            if hasattr(self, 'label'):
                self._refresh_scene_labels()
        
        return super().itemChange(change, value)
    
    def update_connected_wires(self):
        """Update positions of all wires connected to this component"""
        if not hasattr(self, 'connected_wires'):
            return
        
        for wire in self.connected_wires:
            if wire.source == self:
                # Update source end
                pos_term, _ = self.get_terminal_pos()
                wire.setLine(pos_term[0], pos_term[1], wire.line().x2(), wire.line().y2())
            elif wire.target == self:
                # Update target end
                _, neg_term = self.get_terminal_pos()
                wire.setLine(wire.line().x1(), wire.line().y1(), neg_term[0], neg_term[1])
    
    def mouseReleaseEvent(self, event):
        """Snap to grid on mouse release after dragging"""
        # Get current position in pixels
        pos = self.mapToScene(self.boundingRect().center())
        pixel_x = pos.x()
        pixel_y = pos.y()
        
        # Snap to grid
        self.snap_to_grid(pixel_x, pixel_y)
        
        # Reset selection
        self.is_selected = False
        if self.persistent_highlight_color is not None:
            self.update()
        else:
            self.update()
        
        super().mouseReleaseEvent(event)
