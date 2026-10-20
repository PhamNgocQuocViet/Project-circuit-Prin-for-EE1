"""Reconstruct canvas components and wires from validated export data.

The importer maps serialized component IDs back to newly created graphics
items, restores their editable values, and reconnects the recorded terminals.
It mutates only the canvas supplied by the caller.
"""

from components.electrical_component import ElectricalComponent, ComponentType


def reconstruct_circuit_from_dict(circuit_dict, canvas):
    """
    Reconstruct circuit on canvas from serialized data.

    Args:
        circuit_dict: Deserialized circuit dict from JSON
        canvas: Canvas object to place components on
    """
    components = circuit_dict.get("components", [])
    connections = circuit_dict.get("connections", [])
    node_data = circuit_dict.get("nodes", [])

    # Map reference names to component objects for linking
    ref_to_component = {}

    # Step 1: Recreate all components
    for comp_info in components:
        comp_type = ComponentType[comp_info["type"]]
        grid_x = comp_info["grid_x"]
        grid_y = comp_info["grid_y"]
        rotation = comp_info.get("rotation", 0)

        # Create component using factory for consistency
        component = ElectricalComponent(
            comp_type,
            grid_x,
            grid_y,
        )
        
        # Set reference name and display name
        component.reference_name = comp_info.get("reference_name", comp_info["id"])
        component.display_name = comp_info.get("display_name", comp_info["id"])

        # Update the canvas label with reference name (Node components show
        # their assigned name, e.g. "Node A", just like every other component)
        component.update_label_text(component.reference_name)

        # Restore value if not a node
        if comp_type != ComponentType.NODE:
            assigned_value = comp_info.get("assigned_value", "")
            component.value_unit = comp_info.get("value_unit", "")
            if assigned_value:
                component.assigned_value = assigned_value

        # Apply rotation (this updates the visual rotation and terminal positions)
        component.rotation_angle = rotation
        component.setRotation(rotation)

        canvas.scene.addItem(component)
        canvas.components.append(component)
        ref_to_component[comp_info["id"]] = component

    # Labels are counter-rotated and collision-aware, so position them only
    # after every imported component is present in the scene.
    if hasattr(canvas, "refresh_component_labels"):
        canvas.refresh_component_labels()

    # Step 2: Recreate connections with exact terminal information
    for conn_info in connections:
        from_id = conn_info["from"]
        to_id = conn_info["to"]
        from_terminal = conn_info.get("from_terminal", "positive")
        to_terminal = conn_info.get("to_terminal", "negative")

        from_comp = ref_to_component.get(from_id)
        to_comp = ref_to_component.get(to_id)

        if from_comp and to_comp:
            # Recreate the wire with exact terminal connections
            _draw_connection_with_terminals(
                canvas, from_comp, to_comp, from_terminal, to_terminal
            )
            # Also update connections lists for circuit verification
            if to_comp not in from_comp.connections:
                from_comp.connections.append(to_comp)
            if from_comp not in to_comp.connections:
                to_comp.connections.append(from_comp)

    return ref_to_component


def _draw_connection_with_terminals(canvas, comp1, comp2, comp1_terminal, comp2_terminal):
    """
    Draw a wire between components using specific terminals.
    
    Args:
        canvas: CircuitCanvas object
        comp1: First component
        comp2: Second component
        comp1_terminal: "positive" or "negative" for comp1
        comp2_terminal: "positive" or "negative" for comp2
    """
    from PyQt5.QtGui import QPen, QColor
    
    # Get terminal positions
    pos_term1, neg_term1 = comp1.get_terminal_pos()
    pos_term2, neg_term2 = comp2.get_terminal_pos()
    
    # Select which terminal to use based on stored information
    term1 = pos_term1 if comp1_terminal == "positive" else neg_term1
    term2 = pos_term2 if comp2_terminal == "positive" else neg_term2
    
    x1, y1 = term1
    x2, y2 = term2
    
    # Create wire with same styling as canvas
    wire_pen = QPen(QColor(100, 100, 100), canvas.WIRE_WIDTH)
    wire_pen.setCosmetic(True)
    line = canvas.scene.addLine(x1, y1, x2, y2, wire_pen)
    line.source = comp1
    line.target = comp2
    
    # Store wire references in components for updating
    comp1.connected_wires.append(line)
    comp2.connected_wires.append(line)
    
    canvas.connection_lines.append(line)

