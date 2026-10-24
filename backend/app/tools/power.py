from __future__ import annotations

from ..models import Action, CityGraph, CitySnapshot, Impact


def feeder_status(graph: CityGraph, state: CitySnapshot, feeder_id: str) -> dict:
    """READ tool: is this feeder energized?"""
    f = next((x for x in graph.feeders if x.id == feeder_id), None)
    if not f:
        return {"feeder_id": feeder_id, "found": False}
    served = [s.id for s in graph.signals if s.feeder_id == feeder_id]
    dark = [s for s in served if not state.signals_ok.get(s, True)]
    return {
        "feeder_id": feeder_id,
        "found": True,
        "substation_id": f.substation_id,
        "powered": bool(state.powered.get(feeder_id, False)),
        "serves": served,
        "dark_signals": dark,
    }


def substation_status(graph: CityGraph, state: CitySnapshot, substation_id: str) -> dict:
    """READ tool: substation health and downstream darkness."""
    sub = next((x for x in graph.substations if x.id == substation_id), None)
    if not sub:
        return {"substation_id": substation_id, "found": False}
    feeders = []
    dark_signals: list[str] = []
    for fid in sub.feeders:
        powered = bool(state.powered.get(fid, False))
        served = [s.id for s in graph.signals if s.feeder_id == fid]
        dk = [s for s in served if not state.signals_ok.get(s, True)]
        dark_signals.extend(dk)
        feeders.append({"feeder_id": fid, "powered": powered, "serves": served, "dark": dk})
    return {
        "substation_id": substation_id,
        "found": True,
        "node_id": sub.node_id,
        "capacity_mw": sub.capacity_mw,
        "feeders": feeders,
        "total_dark_signals": dark_signals,
    }


def dark_signals(graph: CityGraph, state: CitySnapshot, zone: str | None = None) -> list[dict]:
    """READ tool: all unpowered signals, optionally scoped to a zone."""
    node_zone = {n.id: n.zone for n in graph.nodes}
    out = []
    for s in graph.signals:
        if not state.signals_ok.get(s.id, True):
            z = node_zone.get(s.node_id, "Z0")
            if zone and z != zone:
                continue
            out.append({"signal_id": s.id, "node_id": s.node_id, "feeder_id": s.feeder_id, "zone": z})
    return out


# ---- MUTATE proposals ----


def propose_reroute_feeder(from_feeder: str, to_feeder: str, serves: list[str] | None = None, rationale: str = "") -> Action:
    return Action(
        tool="power.reroute_feeder",
        entity_ids=[from_feeder, to_feeder],
        params={"from_feeder": from_feeder, "to_feeder": to_feeder, "serves": serves or []},
        impact=Impact.HIGH,
        rationale=rationale or "backfeed dark signals from a healthy feeder",
        owner="power",
    )


def propose_restore_substation(substation_id: str, rationale: str = "") -> Action:
    return Action(
        tool="power.restore_substation",
        entity_ids=[substation_id],
        params={"substation_id": substation_id},
        impact=Impact.HIGH,
        rationale=rationale or "restore tripped substation",
        owner="power",
    )


def propose_load_shed(substation_id: str, feeders: list[str], rationale: str = "") -> Action:
    return Action(
        tool="power.load_shed",
        entity_ids=[substation_id],
        params={"substation_id": substation_id, "feeders": feeders},
        impact=Impact.MEDIUM,
        rationale=rationale or "shed load to stabilize substation",
        owner="power",
    )


__all__ = [
    "feeder_status",
    "substation_status",
    "dark_signals",
    "propose_reroute_feeder",
    "propose_restore_substation",
    "propose_load_shed",
]
