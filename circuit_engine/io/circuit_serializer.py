"""Convert the in-memory circuit model to and from the JSON export format.

The serializer records components, selected engineering units, and terminal-
aware wire endpoints. It returns plain Python data or JSON text and performs no
file-system access itself.
"""

import json
from components.electrical_component import ComponentType


def serialize_circuit(components, circuit_name="Untitled Circuit", connection_lines=None):
    """
    Serialize a circuit to JSON-compatible dict.

    Args:
        components: List of component objects on canvas
        circuit_name: Name for the circuit
        connection_lines: List of wire/connection line objects from canvas

    Returns:
        dict: Serializable circuit data
    """
    component_data = []
    connection_data = []
    node_data = []

    # Map components to IDs for reference
    comp_to_id = {}
    for comp in components:
        comp_id = getattr(comp, "reference_name", f"{comp.comp_type.value}_{id(comp)}")
        comp_to_id[id(comp)] = comp_id

        component_data.append({
            "id": comp_id,
            "reference_name": getattr(comp, "reference_name", comp_id),
            "type": comp.comp_type.name,
            "grid_x": comp.grid_x,
            "grid_y": comp.grid_y,
            "rotation": comp.rotation_angle,
            "assigned_value": getattr(comp, "assigned_value", ""),
            "value_unit": getattr(comp, "value_unit", ""),
            "display_name": getattr(comp, "display_name", comp.comp_type.value),
        })

    # Serialize wires with terminal information
    if connection_lines:
        for wire in connection_lines:
            if hasattr(wire, 'source') and hasattr(wire, 'target'):
                source_id = comp_to_id.get(id(wire.source))
                target_id = comp_to_id.get(id(wire.target))
                
                if source_id and target_id:
                    # Get actual wire endpoints to determine which terminal is used
                    line = wire.line()
                    x1, y1 = line.x1(), line.y1()
                    x2, y2 = line.x2(), line.y2()
                    
                    # Get source terminal positions
                    src_pos, src_neg = wire.source.get_terminal_pos()
                    # Get target terminal positions
                    tgt_pos, tgt_neg = wire.target.get_terminal_pos()
                    
                    # Determine which terminals are connected based on wire endpoints
                    # Check if source is positive or negative
                    src_dist_pos = ((x1 - src_pos[0])**2 + (y1 - src_pos[1])**2)**0.5
                    src_dist_neg = ((x1 - src_neg[0])**2 + (y1 - src_neg[1])**2)**0.5
                    src_terminal = "positive" if src_dist_pos < src_dist_neg else "negative"
                    
                    # Check if target is positive or negative
                    tgt_dist_pos = ((x2 - tgt_pos[0])**2 + (y2 - tgt_pos[1])**2)**0.5
                    tgt_dist_neg = ((x2 - tgt_neg[0])**2 + (y2 - tgt_neg[1])**2)**0.5
                    tgt_terminal = "positive" if tgt_dist_pos < tgt_dist_neg else "negative"
                    
                    connection_data.append({
                        "from": source_id,
                        "from_terminal": src_terminal,
                        "to": target_id,
                        "to_terminal": tgt_terminal,
                    })

    # Identify node groups (adjacent nodes are treated as one logical node)
    node_components = [c for c in components if c.comp_type == ComponentType.NODE]
    if node_components:
        visited_nodes = set()
        node_group_id = 1
        for node in node_components:
            if id(node) in visited_nodes:
                continue

            # Find all adjacent nodes (within 1 grid cell)
            group = [node]
            visited_nodes.add(id(node))
            for other_node in node_components:
                if id(other_node) in visited_nodes:
                    continue
                dist = abs(node.grid_x - other_node.grid_x) + abs(node.grid_y - other_node.grid_y)
                if dist <= 1:
                    group.append(other_node)
                    visited_nodes.add(id(other_node))

            node_positions = [(n.grid_x, n.grid_y) for n in group]
            node_ids = [comp_to_id[id(n)] for n in group]
            node_data.append({
                "node_group_id": f"Node_{node_group_id}",
                "node_ids": node_ids,
                "grid_positions": node_positions,
            })
            node_group_id += 1

    return {
        "circuit_name": circuit_name,
        "components": component_data,
        "connections": connection_data,
        "nodes": node_data,
    }


def serialize_to_json(circuit_dict):
    """Convert circuit dict to JSON string."""
    return json.dumps(circuit_dict, indent=2)


def deserialize_from_json(json_str):
    """Parse JSON string to circuit dict."""
    return json.loads(json_str)
