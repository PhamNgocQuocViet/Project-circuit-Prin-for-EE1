"""
Circuit Translator: converts a validated circuit (components + wiring)
into a structured plain-text representation optimized for AI models to
read and reason about using Principles of Electrical Engineering I methods.

This module is export-formatting only: it never touches the circuit graph,
node detection (ui.circuit_checks.netlist), or wiring system -- it only
reads the existing internal net structure (via build_nets/terminal_key)
and renders friendlier, sequential node names and reference labels for the
AI prompt. Internal node/component IDs and canvas reference names are
never modified.
"""

from components.electrical_component import ComponentType
from components.unit_scales import normalize_unit_symbol
from circuit_engine.circuit_checks.netlist import build_nets, terminal_key

TYPE_LABELS = {
    ComponentType.RESISTOR: "Resistor",
    ComponentType.CAPACITOR: "Capacitor",
    ComponentType.INDUCTOR: "Inductor",
    ComponentType.VOLTAGE_SOURCE: "DC Voltage Source",
    ComponentType.CURRENT_SOURCE: "DC Current Source",
}

SOURCE_TYPES = {ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE}


def export_ref(ref):
    """Strip the '#' from a canvas reference name for the AI-facing text (e.g. 'R#1' -> 'R1')."""
    return (ref or "").replace("#", "")


def _alpha_label(index):
    """1 -> 'A', 2 -> 'B', ..., 26 -> 'Z', 27 -> 'AA', ... (matches the canvas Node naming)."""
    label = ""
    n = index
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _alpha_index(label):
    """Inverse of _alpha_label: 'A' -> 1, 'B' -> 2, ..., 'AA' -> 27, ..."""
    index = 0
    for char in label:
        if not char.isalpha():
            return 0
        index = index * 26 + (ord(char.upper()) - 64)
    return index


def _format_value(component):
    """Return an assigned value with normalized units, or ``UNKNOWN``.

    Args:
        component: Value-bearing ElectricalComponent-like object.
    """
    raw_value = (getattr(component, "assigned_value", "") or "").strip()
    if not raw_value:
        return "UNKNOWN"
    symbol = normalize_unit_symbol(
        component.comp_type, getattr(component, "value_unit", "")
    )
    return f"{raw_value} {symbol}".strip()


def _build_node_export_names(components, value_components, reference_name_getter, uf):
    """
    Build the export-only node name mapping (internal net roots are never
    changed). Every net that has a placed Node component keeps that exact
    canvas name (e.g. "Node A") so the AI prompt matches what the user sees
    on screen. Nets with no placed Node component (implicit junctions from
    directly wiring components together) get a generated name continuing
    the same alphabet style (e.g. "Node E" after canvas nodes A-D).
    """
    node_export_names = {}
    node_order = []
    used_indices = set()

    for component in components:
        if component.comp_type != ComponentType.NODE:
            continue
        root = uf.find(terminal_key(component, "positive"))
        if root in node_export_names:
            continue
        name = reference_name_getter(component)
        node_export_names[root] = name
        node_order.append(root)
        index = _alpha_index(name.replace("Node", "").strip())
        if index:
            used_indices.add(index)

    next_index = max(used_indices, default=0)
    for component in value_components:
        for terminal in ("positive", "negative"):
            root = uf.find(terminal_key(component, terminal))
            if root in node_export_names:
                continue
            next_index += 1
            while next_index in used_indices:
                next_index += 1
            used_indices.add(next_index)
            node_export_names[root] = f"Node {_alpha_label(next_index)}"
            node_order.append(root)

    return node_export_names, node_order


def _node_connection_labels(value_components, reference_name_getter, uf):
    """
    Map each net root to the list of connection labels shown under 'Nodes:'.
    Only the plain component reference is listed (e.g. 'R1', 'V1') -- no
    polarity/terminal wording, since that electrical meaning already lives
    in the Source:/Components: definitions above.
    """
    node_connections = {}
    for component in value_components:
        ref = export_ref(reference_name_getter(component))
        pos_root = uf.find(terminal_key(component, "positive"))
        neg_root = uf.find(terminal_key(component, "negative"))
        node_connections.setdefault(pos_root, []).append(ref)
        if neg_root != pos_root:
            node_connections.setdefault(neg_root, []).append(ref)
    return node_connections


def _has_assigned_value(component):
    """Return whether a component contains non-whitespace value text."""
    return bool((getattr(component, "assigned_value", "") or "").strip())


def _solve_target_line(component, target_component):
    """
    Only shown when a component's value is UNKNOWN. It disambiguates the
    two meanings of 'UNKNOWN':
        solve_target: true  -- this IS the requested variable, solve for it
        solve_target: false -- genuinely missing information
    Components with an assigned value never get this line.
    """
    if _has_assigned_value(component):
        return []
    is_target = target_component is not None and component is target_component
    return [f"  solve_target: {'true' if is_target else 'false'}"]


def _source_block(component, reference_name_getter, node_export_names, uf, target_component=None):
    """Build the export lines for one independent source.

    Args:
        component: Source component to describe.
        reference_name_getter: Callable returning its canvas reference.
        node_export_names: Mapping of net roots to AI-facing node names.
        uf: Union-find net structure used to resolve terminal roots.
        target_component: Optional component currently being solved for.
    """
    ref = export_ref(reference_name_getter(component))
    type_label = TYPE_LABELS.get(component.comp_type, component.comp_type.value)
    value_text = _format_value(component)
    pos_name = node_export_names[uf.find(terminal_key(component, "positive"))]
    neg_name = node_export_names[uf.find(terminal_key(component, "negative"))]

    lines = [f" {ref}:", f"  type: {type_label}", f"  value: {value_text}"]
    lines.extend(_solve_target_line(component, target_component))
    if component.comp_type == ComponentType.CURRENT_SOURCE:
        lines.append(f"  direction_from: {pos_name}")
        lines.append(f"  direction_to: {neg_name}")
    else:
        lines.append(f"  positive_node: {pos_name}")
        lines.append(f"  negative_node: {neg_name}")
    return lines


def _component_block(component, reference_name_getter, node_export_names, uf, target_component=None):
    """
    Passive components (Resistor/Capacitor/Inductor) have no fixed polarity
    -- they are described only by the two nodes they connect, never
    'positive'/'negative'. The solver may assume a reference direction
    internally; a negative result then indicates the opposite direction.
    """
    ref = export_ref(reference_name_getter(component))
    type_label = TYPE_LABELS.get(component.comp_type, component.comp_type.value)
    value_text = _format_value(component)
    node_a_name = node_export_names[uf.find(terminal_key(component, "positive"))]
    node_b_name = node_export_names[uf.find(terminal_key(component, "negative"))]
    lines = [
        f"{ref}:",
        f" type: {type_label}",
        f" node_a: {node_a_name}",
        f" node_b: {node_b_name}",
        f" value: {value_text}",
    ]
    lines.extend(_solve_target_line(component, target_component))
    return lines


def _join_blocks(blocks):
    """Join a list of line-lists with a single blank line between each block."""
    lines = []
    for index, block in enumerate(blocks):
        if index > 0:
            lines.append("")
        lines.extend(block)
    return lines


def generate_circuit_export(components, value_component_types, reference_name_getter, connection_lines, target_ref=None):
    """
    Build the AI-facing circuit description ("Circuit:" / "Source:" /
    "Nodes:" / "Components:") using the same node names shown on canvas
    (e.g. "Node A", "Node B", ...) and hash-free reference labels
    (e.g. "R1" instead of "R#1").

    Every component (source or passive) is always described as a real
    circuit element, even when its value is UNKNOWN -- an unknown value is
    a valid EE exam-style question ("Find V1", "Find I1", "Find R1"), not
    missing data. To tell those two cases apart, any component whose value
    is UNKNOWN also gets a `solve_target` flag:
        solve_target: true  -- this is the quantity currently being asked for
        solve_target: false -- unknown but not what's being solved for

    Args:
        target_ref: reference name (e.g. "I1") of the component the current
            AnalysisRequest is asking about, if any.

    Returns:
        str: Plain text circuit description -- see prompt_builder.build_ai_prompt
        for how this is combined with the user's request and instructions.
    """
    value_components = [
        component for component in components
        if component.comp_type in value_component_types
    ]

    if not value_components:
        return "Circuit:\n(No components placed yet.)\n"

    uf = build_nets(components, connection_lines)
    node_export_names, node_order = _build_node_export_names(components, value_components, reference_name_getter, uf)
    node_connections = _node_connection_labels(value_components, reference_name_getter, uf)

    target_component = None
    if target_ref:
        stripped_target_ref = export_ref(target_ref)
        target_component = next(
            (c for c in value_components if export_ref(reference_name_getter(c)) == stripped_target_ref),
            None,
        )

    source_components = [c for c in value_components if c.comp_type in SOURCE_TYPES]
    passive_components = [c for c in value_components if c.comp_type not in SOURCE_TYPES]

    lines = ["Circuit:", "Source:"]
    if source_components:
        source_blocks = [
            _source_block(c, reference_name_getter, node_export_names, uf, target_component) for c in source_components
        ]
        lines.extend(_join_blocks(source_blocks))
    else:
        lines.append(" (none)")

    lines.append("")
    lines.append("")
    lines.append("Nodes:")
    lines.append("")
    node_blocks = []
    for root in node_order:
        connections = node_connections.get(root, [])
        block = [f"{node_export_names[root]}:"]
        if connections:
            block.extend(f" - {conn}" for conn in connections)
        else:
            block.append(" - (no connections)")
        node_blocks.append(block)
    lines.extend(_join_blocks(node_blocks))

    lines.append("")
    lines.append("")
    lines.append("Components:")
    lines.append("")
    if passive_components:
        component_blocks = [
            _component_block(c, reference_name_getter, node_export_names, uf, target_component) for c in passive_components
        ]
        lines.extend(_join_blocks(component_blocks))
    else:
        lines.append(" (none)")

    return "\n".join(lines).rstrip() + "\n"

