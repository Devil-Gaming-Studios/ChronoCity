from __future__ import annotations

from app.city.build_city import build_demo_city, to_networkx
from app.city.cascade import trace_cascade


def test_graph_shape():
    g = build_demo_city()
    assert len(g.nodes) >= 14
    assert len(g.edges) >= 15
    assert g.hospitals[0].node_id == "H1"
    assert g.underpasses[0].edge_id == "E_J4_J6_U1"
    assert {s.id for s in g.substations} == {"S1", "S2"}


def test_networkx_connected():
    import networkx as nx

    g = to_networkx(build_demo_city())
    assert nx.is_weakly_connected(g)


def test_cascade_stops_at_dark_nodes(combined):
    """Root flood edge -> rings of affected (dark) junctions."""
    g = build_demo_city()
    dark = {s.node_id for s in g.signals if not combined.signals_ok.get(s.id, True)}
    blocked = set(combined.flooded_edges)
    assert "E_J4_J6_U1" in blocked
    result = trace_cascade(g, sorted(blocked), blocked_edges=blocked, dark_nodes=dark)
    assert result["contained_hops"] >= 2  # J5, J7, J8, N7 dark downstream
    assert "J5" in result["affected"] or "J7" in result["affected"]


def test_cascade_contained_after_restore(graph, healthy):
    """With everything healthy, only the flood endpoints count (no spread)."""
    blocked = {"E_J4_J6_U1"}
    result = trace_cascade(graph, blocked, blocked_edges=blocked, dark_nodes=set())
    assert result["contained_hops"] == 0
