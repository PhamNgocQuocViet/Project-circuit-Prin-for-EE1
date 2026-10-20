"""
Circuit analysis orchestrator.

Ties together netlist construction, basic wiring checks, series/parallel
topology reduction, and solvability heuristics into the single public
entry point used by the UI: analyze_circuit().
"""

from circuit_engine.circuit_checks.netlist import build_nets
from circuit_engine.circuit_checks.wiring_checks import is_value_component, run_wiring_checks
from circuit_engine.circuit_checks.series_parallel import build_branches, reduce_series_parallel
from circuit_engine.circuit_checks.solvability import build_topology_messages, build_solvability_messages


def analyze_circuit(components, value_component_types, reference_name_getter, connection_lines=None):
    """
    Analyze circuit wiring quality and topology, returning human-readable messages.

    Args:
        components: Iterable of placed components from canvas
        value_component_types: Set of component types that require values
        reference_name_getter: Callable(component) -> str
        connection_lines: Iterable of wire objects (with .source/.target/.line())
            used to build accurate terminal-level connectivity. Optional for
            backward compatibility, but required for topology/solvability checks.

    Returns:
        List[str]: A list of issues/messages.
    """
    value_components = [
        component for component in components
        if is_value_component(component, value_component_types)
    ]
    if not value_components:
        return ["Add components to start circuit checks."]

    # Build electrical nets up-front so the "open circuit" check can look at
    # exact terminal-level wiring instead of guessing from neighbor counts
    # (two wires to the same neighbor, e.g. a direct parallel pair, would
    # otherwise be misreported as an open/dangling connection).
    uf = build_nets(components, connection_lines) if connection_lines is not None else None

    issues = run_wiring_checks(components, value_components, value_component_types, reference_name_getter, uf)
    if issues:
        return issues

    messages = ["Circuit wiring is correct"]

    # --- Topology analysis: build electrical nets and classify series/parallel ---
    if uf is None:
        uf = build_nets(components, connection_lines)
    branches = build_branches(components, value_component_types, uf, reference_name_getter)
    is_series_parallel, remaining_edges, expression = reduce_series_parallel(branches)

    messages.extend(build_topology_messages(is_series_parallel, remaining_edges, expression, branches))
    messages.extend(build_solvability_messages(
        value_components, reference_name_getter, is_series_parallel, branches,
        components=components, value_component_types=value_component_types, connection_lines=connection_lines,
    ))

    return messages
