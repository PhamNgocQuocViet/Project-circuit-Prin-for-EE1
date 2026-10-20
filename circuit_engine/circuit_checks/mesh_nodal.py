"""
Mesh/nodal analysis equation counting for complex (non series-parallel)
networks.

Simple series/parallel reduction fails on "complex" topologies such as
Wheatstone bridges, but that does NOT mean the network is unsolvable —
it just means the simple reduction algebra doesn't apply. Full mesh
(KVL loop) or nodal (KCL) analysis can still solve any connected linear
resistive network with at least one independent source, regardless of
topology.

This module counts the actual independent equations available for a
given netlist (electrical nodes, branches, independent loops, source
current unknowns) to confirm a complex network is well-posed for
mesh/nodal analysis instead of just labelling it "unsolvable".
"""

from components.electrical_component import ComponentType

SOURCE_TYPES = {ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE}


def _distinct_nets(branches):
    """Collect the distinct electrical nets (nodes) touched by a set of branches."""
    nets = set()
    for edge in branches:
        nets.add(edge["a"])
        nets.add(edge["b"])
    return nets


def compute_equation_counts(branches):
    """
    Compute standard circuit-graph equation counts for a set of branches.

    Returns a dict with:
        nodes: number of distinct electrical nets (nodal-analysis nodes)
        branches: number of branches (value-bearing components)
        independent_loops: b - n + 1, the cyclomatic number — the number
            of independent KVL loop/mesh equations available
        node_equations: n - 1, the number of independent KCL node
            equations available (one node chosen as reference/ground)
    """
    nets = _distinct_nets(branches)
    n = len(nets)
    b = len(branches)
    independent_loops = max(b - n + 1, 0)
    node_equations = max(n - 1, 0)
    return {
        "nodes": n,
        "branches": b,
        "independent_loops": independent_loops,
        "node_equations": node_equations,
    }


def is_well_posed(branches, value_components):
    """
    Check whether a network has enough independent equations for full
    mesh/nodal analysis to solve it.

    A connected resistive network with at least one independent source
    always yields a square, well-posed linear system: (n-1) KCL node
    equations plus one voltage/current constraint per source line up
    exactly with the (n-1) node-voltage unknowns plus per-source branch
    currents. This holds regardless of whether the network is series-
    parallel reducible or a "complex" bridge topology — topology only
    changes which solving method (algebraic reduction vs. mesh/nodal
    analysis) applies, not whether a solution exists.
    """
    counts = compute_equation_counts(branches)
    has_source = any(component.comp_type in SOURCE_TYPES for component in value_components)
    return counts["nodes"] >= 2 and has_source


def describe_equation_counts(branches):
    """Human-readable summary of the mesh/nodal equation counts for a network."""
    counts = compute_equation_counts(branches)
    return (
        f"{counts['nodes']} nodes, {counts['node_equations']} independent node (KCL) equations, "
        f"{counts['independent_loops']} independent loop/mesh (KVL) equations"
    )
