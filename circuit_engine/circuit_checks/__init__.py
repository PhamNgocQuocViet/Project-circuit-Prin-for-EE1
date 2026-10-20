"""
Circuit checks package.

This package breaks circuit verification into small, independently
maintainable modules:

- netlist.py          : Union-find electrical net (junction) construction
- wiring_checks.py    : Basic wiring validation (unconnected/open/disconnected)
- series_parallel.py  : Series/parallel reduction and bridge/complex detection
- mesh_nodal.py       : Mesh/nodal equation counting for complex topologies
- solvability.py      : Known/unknown value solvability heuristics
- analyzer.py         : Orchestrates the above into analyze_circuit()

Import `analyze_circuit` from here to run the full circuit analysis pipeline.
"""

from circuit_engine.circuit_checks.analyzer import analyze_circuit

__all__ = ["analyze_circuit"]
