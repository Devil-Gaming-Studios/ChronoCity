from __future__ import annotations

from collections import deque
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
    return {
        "roots": roots,
        "hops": hops,
        "contained_hops": contained_hops,
        "affected": sorted(visited),
    }


__all__ = ["trace_cascade"]
