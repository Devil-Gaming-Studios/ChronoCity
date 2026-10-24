from __future__ import annotations

import heapq

from ..models import Action, CityGraph, CitySnapshot

GRIDLOCK_FACTOR = 2.5  # uncontrolled (dark) junctions slow crossing traffic
BLOCKED_S = 9999.0


def initial_state(graph: CityGraph) -> CitySnapshot:
    """A healthy city: every feeder on, every signal green, no flooding."""
    snap = CitySnapshot(t=0.0)
    for f in graph.feeders:
        snap.powered[f.id] = True
    for sub in graph.substations:
        snap.power_load_mw[sub.id] = round(sub.capacity_mw * 0.65, 2)
    for asset in graph.infrastructure:
        if asset.kind in {"pipeline", "waterway", "water_works", "wastewater_plant"}:
            snap.water_pressure_kpa[asset.id] = 350.0
    for s in graph.signals:
        snap.signals_ok[s.id] = True
        snap.signal_timing_s[s.id] = 60.0
    refresh_travel(snap, graph)
    return snap


def refresh_travel(state: CitySnapshot, graph: CityGraph) -> CitySnapshot:
    """Recompute every edge's travel time from the current state.

    travel = free-flow, then:
      * 9999s if flooded or closed
      * x GRIDLOCK_FACTOR if either endpoint junction has a dark signal
      * x edge_factor (reroute adjustments)
    Pure and deterministic: the twin is always a function of (graph, state).
    """
    node_dark: set[str] = set()
    for sig in graph.signals:
        if not state.signals_ok.get(sig.id, True):
            node_dark.add(sig.node_id)

    for e in graph.edges:
        free = e.length_m / (max(e.free_flow_kph, 1.0) / 3.6)
        if e.id in state.flooded_edges or state.closed_edges.get(e.id, False):
            t = BLOCKED_S
        else:
            t = free * state.edge_factor.get(e.id, 1.0)
            if e.src in node_dark or e.dst in node_dark:
                t *= GRIDLOCK_FACTOR
        state.edge_travel_s[e.id] = t
    return state


def apply_action(state: CitySnapshot, graph: CityGraph, action: Action) -> CitySnapshot:
    """Return a NEW snapshot with one action applied. Pure & deterministic.

    This is the single place mutating tools translate into twin state.
    The simulator calls it; the live twin calls it only after approval.
    """
    s = state.model_copy(deep=True)
    p = action.params
    tool = action.tool

    if tool in ("power.trip_substation", "power.restore_substation"):
        sid = p.get("substation_id") or (action.entity_ids[0] if action.entity_ids else "")
        on = tool.endswith("restore_substation")
        for sub in graph.substations:
            if sub.id == sid:
                for fid in sub.feeders:
                    s.powered[fid] = on
                    for sig in graph.signals:
                        if sig.feeder_id == fid:
                            s.signals_ok[sig.id] = on
                if on:
                    s.failed_assets.pop(sid, None)
                else:
                    s.failed_assets[sid] = "substation trip"
        refresh_travel(s, graph)

    elif tool == "power.set_load":
        sid = p.get("substation_id") or (action.entity_ids[0] if action.entity_ids else "")
        load = max(0.0, float(p.get("load_mw", 0.0)))
        s.power_load_mw[sid] = load
        sub = next((item for item in graph.substations if item.id == sid), None)
        if sub and load > sub.capacity_mw:
            s.failed_assets[sid] = "overload"
            for fid in sub.feeders:
                s.powered[fid] = False
                for sig in graph.signals:
                    if sig.feeder_id == fid:
                        s.signals_ok[sig.id] = False
        refresh_travel(s, graph)

    elif tool == "power.break_line":
        asset_id = str(p.get("asset_id") or (action.entity_ids[0] if action.entity_ids else ""))
        s.failed_assets[asset_id] = "power line break"
        sid = p.get("substation_id")
        if sid:
            for sub in graph.substations:
                if sub.id == sid:
                    for fid in sub.feeders:
                        s.powered[fid] = False
                        for sig in graph.signals:
                            if sig.feeder_id == fid:
                                s.signals_ok[sig.id] = False
        refresh_travel(s, graph)

    elif tool == "power.reroute_feeder":
        # move a feeder's served signals onto a healthy source feeder
        fid = p.get("from_feeder", "")
        target = p.get("to_feeder", "")
        serves = p.get("serves") or []
        if not serves:
            for f in graph.feeders:
                if f.id == fid:
                    serves = list(f.serves)
        target_on = bool(s.powered.get(target, False))
        for sig in graph.signals:
            if sig.id in serves:
                s.signals_ok[sig.id] = target_on
        refresh_travel(s, graph)

    elif tool == "power.load_shed":
        # shedding kills the feeders AND the signals they serve
        for fid in p.get("feeders", []):
            s.powered[fid] = False
            for sig in graph.signals:
                if sig.feeder_id == fid:
                    s.signals_ok[sig.id] = False
        refresh_travel(s, graph)

    elif tool == "traffic.flood_edge":
        eid = p.get("edge_id", "")
        s.flooded_edges[eid] = float(p.get("depth_cm", 100.0))
        refresh_travel(s, graph)

    elif tool == "traffic.clear_flood":
        s.flooded_edges.pop(p.get("edge_id", ""), None)
        refresh_travel(s, graph)

    elif tool == "traffic.close_edge":
        s.closed_edges[p.get("edge_id", "")] = True
        refresh_travel(s, graph)

    elif tool == "traffic.set_congestion":
        edge_id = str(p.get("edge_id") or (action.entity_ids[0] if action.entity_ids else ""))
        s.edge_factor[edge_id] = max(s.edge_factor.get(edge_id, 1.0), float(p.get("factor", 2.0)))
        refresh_travel(s, graph)

    elif tool == "traffic.reroute":
        # factor adjusts edge preference; refresh_travel applies it
        slow = p.get("slow_edge_id")
        fast = p.get("fast_edge_id")
        if slow:
            s.edge_factor[slow] = max(s.edge_factor.get(slow, 1.0), float(p.get("factor", 2.0)))
        if fast:
            s.edge_factor[fast] = min(s.edge_factor.get(fast, 1.0), 0.7)
        refresh_travel(s, graph)

    elif tool == "traffic.signal_dark":
        for sid in p.get("signal_ids", action.entity_ids):
            s.signals_ok[sid] = False
        refresh_travel(s, graph)

    elif tool == "traffic.retime_signals":
        timing = max(10.0, float(p.get("cycle_s", 60.0)))
        for sid in p.get("signal_ids", action.entity_ids):
            s.signal_timing_s[sid] = timing
        refresh_travel(s, graph)

    elif tool == "water.break_pipe":
        asset_id = str(p.get("asset_id") or (action.entity_ids[0] if action.entity_ids else ""))
        s.water_failures[asset_id] = "pipe break"
        s.failed_assets[asset_id] = "pipe break"
        s.water_pressure_kpa[asset_id] = 0.0

    elif tool == "water.set_pressure":
        asset_id = str(p.get("asset_id") or (action.entity_ids[0] if action.entity_ids else ""))
        pressure = max(0.0, float(p.get("pressure_kpa", 0.0)))
        s.water_pressure_kpa[asset_id] = pressure
        if pressure < 20.0:
            s.water_failures[asset_id] = "low pressure"
            s.failed_assets[asset_id] = "low pressure"

    elif tool == "water.repair_pipe":
        asset_id = str(p.get("asset_id") or (action.entity_ids[0] if action.entity_ids else ""))
        s.water_failures.pop(asset_id, None)
        s.failed_assets.pop(asset_id, None)
        s.water_pressure_kpa[asset_id] = 350.0

    elif tool == "emergency.dispatch":
        amb = p.get("ambulance_id", "A1")
        s.ambulances.setdefault(amb, {})
        s.ambulances[amb]["edge_id"] = p.get("from_edge", "")
        s.ambulances[amb]["status"] = "dispatched"

    elif tool == "emergency.set_destination":
        amb = p.get("ambulance_id", "A1")
        s.ambulances.setdefault(amb, {})
        s.ambulances[amb]["dest"] = p.get("dest_node", "H1")

    elif tool == "emergency.activate_shelter":
        shelter_id = str(p.get("shelter_id") or (action.entity_ids[0] if action.entity_ids else ""))
        s.shelters.setdefault(shelter_id, {})
        s.shelters[shelter_id].update({"active": True, "available": p.get("available", 0)})

    # unknown tools are ignored (defence-in-depth; the registry rejects them earlier)
    return s


def reachable_travel_time(state: CitySnapshot, graph: CityGraph, src: str, dst: str) -> float:
    """Dijkstra over live edge travel times. Blocked edges (9999) are avoided."""
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in graph.edges:
        adj.setdefault(e.src, []).append((e.dst, e.id))
        adj.setdefault(e.dst, []).append((e.src, e.id))

    dist: dict[str, float] = {src: 0.0}
    pq: list[tuple[float, str]] = [(0.0, src)]
    seen: set[str] = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        if u == dst:
            return d
        for v, eid in adj.get(u, []):
            wt = state.edge_travel_s.get(eid, BLOCKED_S)
            if wt >= BLOCKED_S:
                continue
            nd = d + wt
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return float("inf")


def advance_tick(state: CitySnapshot, graph: CityGraph, seconds: float = 1.0) -> CitySnapshot:
    """Advance the deterministic twin clock without mutating the input snapshot."""
    s = state.model_copy(deep=True)
    s.t += max(0.0, seconds)
    # Floodwater recedes slowly; congestion decays toward free flow.
    for edge_id, depth in list(s.flooded_edges.items()):
        next_depth = max(0.0, depth - seconds * 0.5)
        if next_depth <= 0.0:
            s.flooded_edges.pop(edge_id, None)
        else:
            s.flooded_edges[edge_id] = next_depth
    for edge_id, factor in list(s.edge_factor.items()):
        next_factor = max(1.0, factor - seconds * 0.02)
        if next_factor <= 1.0:
            s.edge_factor.pop(edge_id, None)
        else:
            s.edge_factor[edge_id] = next_factor
    refresh_travel(s, graph)
    return s


__all__ = ["initial_state", "apply_action", "advance_tick", "reachable_travel_time", "refresh_travel", "GRIDLOCK_FACTOR", "BLOCKED_S"]
