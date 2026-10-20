"""
Series/parallel network reduction and complex (bridge) topology detection.

Converts value-bearing components into graph edges ("branches") between
electrical nets, then repeatedly applies parallel-merge and series-
contraction steps until the network collapses to a single equivalent edge
(series-parallel network) or reduction stalls (a "complex"/bridge network
that requires mesh/nodal analysis).
"""

from components.electrical_component import ComponentType
from circuit_engine.circuit_checks.netlist import terminal_key
from circuit_engine.circuit_checks.wiring_checks import is_value_component


def build_branches(components, value_component_types, uf, reference_name_getter):
    """Build one graph edge ("branch") per value-bearing component (nodes excluded)."""
    branches = []
    for component in components:
        if component.comp_type == ComponentType.NODE:
            continue
        if not is_value_component(component, value_component_types):
            continue

        net_pos = uf.find(terminal_key(component, "positive"))
        net_neg = uf.find(terminal_key(component, "negative"))
        ref = reference_name_getter(component)
        branches.append({
            "a": net_pos,
            "b": net_neg,
            "expr": ref,
            "refs": [ref],
        })
    return branches


def walk_pure_series_loop(branches):
    """
    Detect the common special case of a single unbranched loop (every net
    touches exactly 2 branch terminals, forming one simple cycle across
    >=3 distinct nets). Returns an ordered list of branches walked around
    the loop, or None if the network isn't a simple single loop.

    This avoids reporting a plain series loop (e.g. V-R1-R2 in one ring)
    as a confusing "parallel" combination, which is what the generic
    series/parallel graph reduction would otherwise produce for any
    3+ node cycle.
    """
    if len(branches) < 3:
        return None

    adjacency = {}
    for idx, edge in enumerate(branches):
        adjacency.setdefault(edge["a"], []).append(idx)
        adjacency.setdefault(edge["b"], []).append(idx)

    # A genuine simple cycle has exactly as many distinct nets as branches,
    # and every net touches exactly 2 branch terminals.
    if len(adjacency) != len(branches):
        return None
    if any(len(indices) != 2 for indices in adjacency.values()):
        return None

    order = [branches[0]]
    visited_edges = {0}
    current_vertex = branches[0]["b"]

    for _ in range(len(branches) - 1):
        candidates = [i for i in adjacency.get(current_vertex, []) if i not in visited_edges]
        if not candidates:
            return None
        next_idx = candidates[0]
        next_edge = branches[next_idx]
        order.append(next_edge)
        visited_edges.add(next_idx)
        current_vertex = next_edge["b"] if next_edge["a"] == current_vertex else next_edge["a"]

    if len(visited_edges) != len(branches):
        return None
    return order


def reduce_series_parallel(branches):
    """
    Reduce a multigraph of branches (nets as vertices, components as edges)
    using repeated parallel-merge and series-contraction steps.

    Returns:
        (is_series_parallel, remaining_edges, expression)
        - is_series_parallel: True if the whole network collapses to 1 edge
        - remaining_edges: final edge list (len 1 if fully reducible)
        - expression: human-readable equivalent network expression
    """
    if not branches:
        return True, [], ""

    # Special case: a single unbranched loop reads far more naturally as a
    # plain series chain than as the "(a || (b + c))" form the generic
    # graph-reduction below would otherwise produce for a 3+ node cycle.
    loop_order = walk_pure_series_loop(branches)
    if loop_order is not None:
        expr = " + ".join(edge["expr"] for edge in loop_order)
        refs = [ref for edge in loop_order for ref in edge["refs"]]
        return True, [{"a": None, "b": None, "expr": expr, "refs": refs}], expr

    edges = [dict(edge) for edge in branches]

    max_iterations = max(50, len(edges) * 25)
    for _ in range(max_iterations):
        changed = False

        # 1) Merge parallel edges (same unordered net pair)
        groups = {}
        for edge in edges:
            if edge["a"] == edge["b"]:
                key = ("loop", edge["a"])
            else:
                key = frozenset((edge["a"], edge["b"]))
            groups.setdefault(key, []).append(edge)

        merged_edges = []
        for group in groups.values():
            if len(group) > 1:
                combined_refs = []
                for edge in group:
                    combined_refs.extend(edge["refs"])
                expr = "(" + " \u2225 ".join(edge["expr"] for edge in group) + ")"
                merged_edges.append({
                    "a": group[0]["a"],
                    "b": group[0]["b"],
                    "expr": expr,
                    "refs": combined_refs,
                })
                changed = True
            else:
                merged_edges.append(group[0])
        edges = merged_edges

        if changed:
            continue

        # 2) Contract any vertex with exactly two distinct incident edges (series)
        degree = {}
        for edge in edges:
            degree[edge["a"]] = degree.get(edge["a"], 0) + 1
            degree[edge["b"]] = degree.get(edge["b"], 0) + 1

        for vertex, deg in degree.items():
            if deg != 2:
                continue
            incident = [edge for edge in edges if edge["a"] == vertex or edge["b"] == vertex]
            if len(incident) != 2 or incident[0] is incident[1]:
                continue

            edge1, edge2 = incident
            other1 = edge1["b"] if edge1["a"] == vertex else edge1["a"]
            other2 = edge2["b"] if edge2["a"] == vertex else edge2["a"]
            if other1 == vertex or other2 == vertex:
                continue  # skip degenerate self-loop cases

            new_edge = {
                "a": other1,
                "b": other2,
                "expr": f"({edge1['expr']} + {edge2['expr']})",
                "refs": edge1["refs"] + edge2["refs"],
            }
            edges = [edge for edge in edges if edge is not edge1 and edge is not edge2]
            edges.append(new_edge)
            changed = True
            break

        if not changed:
            break

    is_series_parallel = len(edges) == 1
    expression = edges[0]["expr"] if edges else ""
    return is_series_parallel, edges, expression
