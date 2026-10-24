from __future__ import annotations

import networkx as nx

from ..models import Action, CityGraph, CitySnapshot, Impact
from ..sim.state import reachable_travel_time


def shortest_route(graph: CityGraph, state: CitySnapshot, src: str, dst: str) -> dict:
    """READ tool: fastest route under current live travel times."""
    import heapq

    edges = {e.id: e for e in graph.edges}
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in graph.edges:
        adj.setdefault(e.src, []).append((e.dst, e.id))
        adj.setdefault(e.dst, []).append((e.src, e.id))

    dist = {src: 0.0}
    prev: dict[str, tuple[str, str]] = {}
    pq: list[tuple[float, str]] = [(0.0, src)]
    seen: set[str] = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        if u == dst:
            break
        for v, eid in adj.get(u, []):
            wt = state.edge_travel_s.get(eid, 9999.0)
            if wt >= 9999.0:
                continue
            nd = d + wt
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, eid)
                heapq.heappush(pq, (nd, v))

    if dst not in dist:
        return {"src": src, "dst": dst, "reachable": False, "travel_s": float("inf"), "edges": [], "nodes": []}

    # reconstruct
    path_edges: list[str] = []
    path_nodes: list[str] = [dst]
    cur = dst
    while cur != src:
        u, eid = prev[cur]
        path_edges.append(eid)
        path_nodes.append(u)
        cur = u
    path_edges.reverse()
    path_nodes.reverse()
    return {
        "src": src,
        "dst": dst,
        "reachable": True,
        "travel_s": round(dist[dst], 2),
        "edges": path_edges,
        "nodes": path_nodes,
    }


def edge_status(graph: CityGraph, state: CitySnapshot, edge_id: str) -> dict:
    """READ tool: is this edge flooded / closed / clear?"""
    e = next((x for x in graph.edges if x.id == edge_id), None)
    if not e:
        return {"edge_id": edge_id, "found": False}
    return {
        "edge_id": edge_id,
        "found": True,
        "src": e.src,
        "dst": e.dst,
        "kind": e.kind,
        "flooded": edge_id in state.flooded_edges,
        "depth_cm": state.flooded_edges.get(edge_id, 0.0),
        "travel_s": round(state.edge_travel_s.get(edge_id, 0.0), 2),
        "blocked": state.edge_travel_s.get(edge_id, 0.0) >= 9999.0,
    }


def congestion_map(graph: CityGraph, state: CitySnapshot) -> list[dict]:
    """READ tool: edges sorted by how bad they are right now."""
    out = []
    for e in graph.edges:
        t = state.edge_travel_s.get(e.id, 0.0)
        free = e.length_m / (max(e.free_flow_kph, 1.0) / 3.6)
        ratio = t / free if free else 1.0
        out.append({"edge_id": e.id, "travel_s": round(t, 2), "free_s": round(free, 2), "congestion": round(ratio, 2)})
    out.sort(key=lambda d: -d["congestion"])
    return out


# ---- MUTATE proposals (returned as Action, never executed directly) ----


def propose_close_edge(edge_id: str, rationale: str = "") -> Action:
    return Action(
        tool="traffic.close_edge",
        entity_ids=[edge_id],
        params={"edge_id": edge_id},
        impact=Impact.MEDIUM,
        rationale=rationale or "close impassable edge",
        owner="traffic",
    )


def propose_flood_edge(edge_id: str, depth_cm: float, rationale: str = "") -> Action:
    return Action(
        tool="traffic.flood_edge",
        entity_ids=[edge_id],
        params={"edge_id": edge_id, "depth_cm": depth_cm},
        impact=Impact.HIGH,
        rationale=rationale or "mark edge flooded",
        owner="traffic",
    )


def propose_reroute(slow_edge_id: str, fast_edge_id: str, factor: float = 2.0, rationale: str = "") -> Action:
    return Action(
        tool="traffic.reroute",
        entity_ids=[slow_edge_id, fast_edge_id],
        params={"slow_edge_id": slow_edge_id, "fast_edge_id": fast_edge_id, "factor": factor},
        impact=Impact.LOW,
        rationale=rationale or "shift load off congested edge",
        owner="traffic",
    )


__all__ = [
    "shortest_route",
    "edge_status",
    "congestion_map",
    "propose_close_edge",
    "propose_flood_edge",
    "propose_reroute",
]
