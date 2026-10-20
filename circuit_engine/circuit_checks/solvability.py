"""
Solvability heuristics based on known/unknown component values.

Given a circuit's value components and its series/parallel reduction
result, determine whether the circuit has a power source, how many
values are still missing, and -- when exactly one value is missing --
verify via the actual DC solver whether that single unknown is genuinely,
uniquely determined by the rest of the circuit (not just "the topology is
reducible", which is necessary but not sufficient: e.g. a resistor in
series with a voltage source, sitting in parallel with other branches,
can be topologically series-parallel-reducible yet still mathematically
underdetermined for that resistor's value).
"""

from components.electrical_component import ComponentType
from circuit_engine.circuit_checks.mesh_nodal import describe_equation_counts, is_well_posed

SOURCE_TYPES = {ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE}


def build_topology_messages(is_series_parallel, remaining_edges, expression, branches=None):
    """Return messages describing the equivalent network or complex topology."""
    messages = []
    if is_series_parallel and expression:
        messages.append(f"Equivalent network: {expression}")
    elif remaining_edges:
        remaining_refs = sorted({ref for edge in remaining_edges for ref in edge["refs"]})
        refs_text = ", ".join(remaining_refs[:6])
        equation_summary = describe_equation_counts(branches) if branches else ""
        detail = f" ({equation_summary})" if equation_summary else ""
        messages.append(
            f"Complex topology detected (e.g., bridge network) around: {refs_text}. "
            f"Simple series-parallel reduction does not apply; solvable via full mesh/nodal analysis{detail}."
        )
    return messages


def _check_single_unknown_solvable(components, value_component_types, reference_name_getter, connection_lines):
    """
    The internal numeric DC solver has been retired in favor of the
    AI-assisted analysis workflow (see ui/ai_assistant). Topology-based
    solvability heuristics below still run; this hook simply reports
    "unknown" so callers fall back to those heuristics.
    """
    return None, ""


def build_solvability_messages(
    value_components, reference_name_getter, is_series_parallel, branches=None,
    components=None, value_component_types=None, connection_lines=None,
):
    """Return messages describing whether the circuit can be solved given known/unknown values."""
    has_source = any(component.comp_type in SOURCE_TYPES for component in value_components)
    missing = [
        component for component in value_components
        if not getattr(component, "assigned_value", "").strip()
    ]

    if not has_source:
        return ["No power source (Voltage/Current Source) present; circuit cannot be solved."]

    if len(missing) == 0:
        return ["All component values are known; circuit is fully defined."]

    if len(missing) > 1:
        refs = ", ".join(reference_name_getter(component) for component in missing[:4])
        return [
            f"{len(missing)} values are missing ({refs}); provide all but one value to solve for a single unknown."
        ]

    target = reference_name_getter(missing[0])

    # With exactly one unknown, verify against the real solver whether it is
    # genuinely determined by the rest of the circuit (topology alone isn't
    # enough -- see module docstring).
    solvable = None
    detail = ""
    if components is not None and value_component_types is not None and connection_lines is not None:
        solvable, detail = _check_single_unknown_solvable(
            components, value_component_types, reference_name_getter, connection_lines
        )

    if solvable is False:
        return [
            f"Circuit has 1 unknown value ({target}), but it cannot be solved from the other "
            f"known values: {detail}"
        ]

    if is_series_parallel:
        return [f"Circuit is solvable for {target} using series-parallel reduction."]

    if branches is not None and is_well_posed(branches, value_components):
        equation_summary = describe_equation_counts(branches)
        return [
            f"Circuit has 1 unknown value ({target}) in a complex (non series-parallel) topology, "
            f"but is still solvable for {target} using full mesh/nodal analysis ({equation_summary})."
        ]

    return [
        f"Circuit has 1 unknown value ({target}), but its complex topology requires mesh/nodal "
        "analysis rather than simple series-parallel reduction."
    ]

