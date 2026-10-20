"""
Electrical netlist construction.

Builds "nets" (electrically-equivalent junction groups) across every
component terminal using a union-find structure. Two terminals end up in
the same net if they are joined by a wire, or if they belong to the same
Node component (which fuses its own two terminals into one junction).
"""

from components.electrical_component import ComponentType


class UnionFind:
    """Simple union-find (disjoint set) over hashable keys."""

    def __init__(self):
        """Create an empty disjoint-set parent mapping."""
        self.parent = {}

    def find(self, key):
        """Return key's representative root, applying path compression."""
        self.parent.setdefault(key, key)
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        # Path compression
        while self.parent[key] != root:
            self.parent[key], key = root, self.parent[key]
        return root

    def union(self, a, b):
        """Merge the sets containing hashable keys a and b."""
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_a] = root_b


def terminal_key(component, terminal):
    """Unique hashable key for one terminal of one component instance."""
    return (id(component), terminal)


def wire_terminal_sides(wire):
    """
    Determine which terminal ('positive'/'negative') of wire.source and
    wire.target a wire actually connects to, based on the wire's drawn
    endpoints versus each component's live terminal positions.
    """
    source = getattr(wire, "source", None)
    target = getattr(wire, "target", None)
    if source is None or target is None:
        return "positive", "negative"

    try:
        line = wire.line()
        x1, y1, x2, y2 = line.x1(), line.y1(), line.x2(), line.y2()
    except AttributeError:
        return "positive", "negative"

    def _closer_terminal(point, pos_point, neg_point):
        """Return the terminal name geometrically closest to point."""
        dist_pos = (point[0] - pos_point[0]) ** 2 + (point[1] - pos_point[1]) ** 2
        dist_neg = (point[0] - neg_point[0]) ** 2 + (point[1] - neg_point[1]) ** 2
        return "positive" if dist_pos <= dist_neg else "negative"

    src_pos, src_neg = source.get_terminal_pos()
    tgt_pos, tgt_neg = target.get_terminal_pos()

    src_terminal = _closer_terminal((x1, y1), src_pos, src_neg)
    tgt_terminal = _closer_terminal((x2, y2), tgt_pos, tgt_neg)
    return src_terminal, tgt_terminal


def build_nets(components, connection_lines):
    """
    Build electrical nets (junction groups) across all component terminals.

    Node components fuse their own positive/negative terminals together
    (they are a single physical junction point). Wires union whichever
    terminals they actually connect, based on drawn geometry.

    Returns:
        UnionFind: ready to query with .find(terminal_key(component, side))
    """
    uf = UnionFind()

    for component in components:
        uf.find(terminal_key(component, "positive"))
        uf.find(terminal_key(component, "negative"))
        if component.comp_type == ComponentType.NODE:
            uf.union(terminal_key(component, "positive"), terminal_key(component, "negative"))

    for wire in connection_lines or []:
        source = getattr(wire, "source", None)
        target = getattr(wire, "target", None)
        if source is None or target is None:
            continue
        src_terminal, tgt_terminal = wire_terminal_sides(wire)
        uf.union(terminal_key(source, src_terminal), terminal_key(target, tgt_terminal))

    return uf
