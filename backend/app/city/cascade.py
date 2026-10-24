from __future__ import annotations

from collections import deque

import networkx as nx
from typing import Iterable

from ..models import CityGraph
from .build_city import to_networkx


def trace_cascade(
    graph: CityGraph,
    root_entity_ids: Iterable[str],
    blocked_edges: set[str] | None = None,
    dark_nodes: set[str] | None = None,
    max_hops: int = 6,
) -> dict[str, object]:
    """Trace how a root failure propagates through the city.

    An entity is *affected* if it is a dark-signal junction or an endpoint of
    a flooded/closed edge. Cascade hops are rings of affected nodes reachable
    from the root through other affected nodes — healthy junctions are not
    part of the cascade (they are just adjacent infrastructure).

    Returns hops: [{"hop": int, "entities": [...]}] and contained_hops: the
    deepest ring reached (0 means the failure is local).
    """
    g = to_networkx(graph)
    blocked_edges = blocked_edges or set()
    dark_nodes = dark_nodes or set()

    node_ids = set(g.nodes)
    edge_endpoints: dict[str, list[str]] = {}
    for _u, _v, data in g.edges(data=True):
        eid = str(data.get("id", ""))
        base = eid[:-4] if eid.endswith("_rev") else eid
        edge_endpoints.setdefault(base, [])

    # affected nodes = dark junctions + endpoints of blocked edges
    affected: set[str] = set(dark_nodes)
    for u, v, data in g.edges(data=True):
        eid = str(data.get("id", ""))
        base = eid[:-4] if eid.endswith("_rev") else eid
        if base in blocked_edges:
            affected.add(u)
            affected.add(v)

    # normalize roots (node ids or edge ids) to nodes
    roots: list[str] = []
    for rid in root_entity_ids:
        if rid in node_ids:
            roots.append(rid)
        elif rid in blocked_edges:
            for u, v, data in g.edges(data=True):
                if str(data.get("id", "")) in (rid, rid + "_rev"):
                    roots.extend([u, v])
    roots = [n for n in dict.fromkeys(roots) if n in affected] or [n for n in dict.fromkeys(roots)]

    visited: set[str] = set(roots)
    hops: list[dict[str, object]] = [{"hop": 0, "entities": roots}]
    frontier: deque[tuple[str, int]] = deque((r, 0) for r in roots)

    while frontier:
        node, depth = frontier.popleft()
        if depth >= max_hops:
            continue
        nxt: list[str] = []
        for _u, v, _data in g.edges(node, data=True):
            if v in visited or v not in affected:
                continue
            visited.add(v)
            nxt.append(v)
        if nxt:
            hops.append({"hop": depth + 1, "entities": nxt})
            frontier.extend((n, depth + 1) for n in nxt)

    contained_hops = max((int(h["hop"]) for h in hops), default=0)
    chain: list[str] = []
    if blocked_edges:
        chain.append("flood -> road blocked")
    if dark_nodes:
        chain.extend(["road blockage -> emergency reroute", "substation trip -> signals dark", "signals dark -> gridlock", "gridlock -> ambulance delay"])
    return {
        "roots": roots,
        "hops": hops,
        "contained_hops": contained_hops,
        "affected": sorted(visited),
        "chain": chain,
    }


def build_dependency_graph(graph: CityGraph) -> nx.MultiDiGraph:
    """Build a cross-domain dependency graph used by the orchestrator and audit tools.

    Nodes are typed as road, power, water, emergency, hospital, shelter, or signal.
    Edges describe physical service and operational dependencies.
    """
    g = nx.MultiDiGraph()
    for node in graph.nodes:
        g.add_node(node.id, domain=node.kind, name=node.name, zone=node.zone)
    for edge in graph.edges:
        g.add_node(edge.id, domain="traffic", kind=edge.kind)
        g.add_edge(edge.src, edge.id, relation="road_endpoint")
        g.add_edge(edge.id, edge.dst, relation="road_endpoint")
    for sub in graph.substations:
        g.add_node(sub.id, domain="power")
        g.add_edge(sub.id, sub.node_id, relation="powers_site")
    for feeder in graph.feeders:
        g.add_node(feeder.id, domain="power")
        g.add_edge(feeder.substation_id, feeder.id, relation="feeds")
        for served in feeder.serves:
            signal = next((item for item in graph.signals if item.id == served), None)
            if signal:
                g.add_node(signal.id, domain="signal")
                g.add_edge(feeder.id, signal.id, relation="powers")
                g.add_edge(signal.id, signal.node_id, relation="controls")
    for hospital in graph.hospitals:
        g.add_node(hospital.id, domain="emergency")
        g.add_edge(hospital.node_id, hospital.id, relation="serves")
    for shelter in graph.shelters:
        g.add_node(shelter.id, domain="emergency")
        g.add_edge(shelter.node_id, shelter.id, relation="serves")
    for asset in graph.infrastructure:
        g.add_node(asset.id, domain=asset.kind)
        if asset.geometry:
            asset_points = asset.geometry
            for node in graph.nodes:
                if any((x - node.x) ** 2 + (y - node.y) ** 2 < 0.35 ** 2 for x, y in asset_points):
                    g.add_edge(asset.id, node.id, relation="near")
            for edge in graph.edges:
                endpoints = [(next((n.x for n in graph.nodes if n.id == edge.src), 0.0), next((n.y for n in graph.nodes if n.id == edge.src), 0.0)),
                             (next((n.x for n in graph.nodes if n.id == edge.dst), 0.0), next((n.y for n in graph.nodes if n.id == edge.dst), 0.0))]
                if any((x - ex) ** 2 + (y - ey) ** 2 < 0.35 ** 2 for x, y in asset_points for ex, ey in endpoints):
                    g.add_edge(asset.id, edge.id, relation="near")
    return g


__all__ = ["trace_cascade", "build_dependency_graph"]
