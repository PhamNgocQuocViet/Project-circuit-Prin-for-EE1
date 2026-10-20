"""
Basic wiring validation checks.

These checks catch structural wiring mistakes before any deeper topology
or solvability analysis is attempted: missing minimum components, wires
that were never connected, dangling/open terminals, and groups of
components that aren't connected to the rest of the circuit.
"""

from components.electrical_component import ComponentType
from circuit_engine.circuit_checks.netlist import build_nets, terminal_key


def is_value_component(component, value_component_types):
    """Return whether component belongs to a value-bearing type set."""
    return component.comp_type in value_component_types


def check_minimum_components(value_components):
    """Require at least 2 value-bearing components to form a circuit."""
    if len(value_components) < 2:
        return ["Invalid circuit: at least 2 value components are required."]
    return []


def check_unconnected(value_components, reference_name_getter):
    """Flag value components with zero wire connections."""
    unconnected = [component for component in value_components if len(component.connections) == 0]
    if not unconnected:
        return []
    refs = ", ".join(reference_name_getter(component) for component in unconnected[:3])
    return [f"Wires not connected for: {refs}"]


def check_open_terminals(components, value_components, reference_name_getter, uf):
    """
    Flag components with a dangling (unconnected) terminal.

    Uses terminal-level net sizes so that two wires to the same neighbor
    (a valid parallel connection) is never mistaken for a dangling wire.
    """
    if uf is not None:
        net_sizes = {}
        for component in components:
            for terminal in ("positive", "negative"):
                root = uf.find(terminal_key(component, terminal))
                net_sizes[root] = net_sizes.get(root, 0) + 1

        def _terminal_is_isolated(component, terminal):
            """Return whether one terminal remains in its original singleton net."""
            root = uf.find(terminal_key(component, terminal))
            return net_sizes.get(root, 1) <= 1

        open_nodes = [
            component for component in value_components
            if len(component.connections) > 0 and (
                _terminal_is_isolated(component, "positive")
                or _terminal_is_isolated(component, "negative")
            )
        ]
    else:
        # Fallback for callers that don't supply wire objects.
        open_nodes = [component for component in value_components if len(component.connections) < 2]

    if not open_nodes:
        return []
    refs = ", ".join(reference_name_getter(component) for component in open_nodes[:3])
    return [f"Circuit is open near: {refs}"]


def check_disconnected_groups(components, value_component_types):
    """Flag when the circuit splits into multiple unconnected component groups."""
    connected_relevant = [
        component for component in components
        if len(component.connections) > 0 and (
            is_value_component(component, value_component_types)
            or component.comp_type == ComponentType.NODE
        )
    ]

    if not connected_relevant:
        return []

    visited = set()
    stack = [connected_relevant[0]]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in current.connections:
            if neighbor not in visited:
                stack.append(neighbor)

    disconnected = [component for component in connected_relevant if component not in visited]
    if disconnected:
        return ["Invalid circuit: disconnected groups detected."]
    return []


def run_wiring_checks(components, value_components, value_component_types, reference_name_getter, uf):
    """Run all basic wiring checks in order, returning the combined issue list."""
    issues = []
    issues.extend(check_minimum_components(value_components))
    issues.extend(check_unconnected(value_components, reference_name_getter))
    issues.extend(check_open_terminals(components, value_components, reference_name_getter, uf))
    issues.extend(check_disconnected_groups(components, value_component_types))
    return issues
