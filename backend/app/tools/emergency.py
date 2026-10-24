from __future__ import annotations

from ..models import Action, CityGraph, CitySnapshot, Impact
from ..sim.state import reachable_travel_time


def ambulance_eta(graph: CityGraph, state: CitySnapshot, ambulance_id: str = "A1", dest_node: str = "H1") -> dict:
    """READ tool: current ETA for an ambulance to its destination hospital."""
    # ambulances originate from the depot node in this demo
    src = "DEPOT"
    tt = reachable_travel_time(state, graph, src, dest_node)
    return {
        "ambulance_id": ambulance_id,
        "from": src,
        "dest": dest_node,
        "reachable": tt != float("inf"),
        "eta_s": round(tt, 2) if tt != float("inf") else None,
    }


def hospital_access(graph: CityGraph, state: CitySnapshot, hospital_id: str = "H1") -> dict:
    """READ tool: is the hospital reachable and via which approaches are open."""
    hosp = next((h for h in graph.hospitals if h.id == hospital_id), None)
    if not hosp:
        return {"hospital_id": hospital_id, "found": False}
    approaches = []
    for e in graph.edges:
        if e.src == hosp.node_id or e.dst == hosp.node_id:
            other = e.dst if e.src == hosp.node_id else e.src
            blocked = state.edge_travel_s.get(e.id, 0.0) >= 9999.0
            approaches.append({"edge_id": e.id, "to_node": other, "blocked": blocked})
    return {
        "hospital_id": hospital_id,
        "found": True,
        "node_id": hosp.node_id,
        "approaches": approaches,
        "any_open": any(not a["blocked"] for a in approaches),
    }


def response_units(graph: CityGraph, state: CitySnapshot) -> list[dict]:
    """READ tool: known ambulances and their status."""
    out = []
    for aid, info in state.ambulances.items():
        out.append({"ambulance_id": aid, **info})
    if not out:
        out.append({"ambulance_id": "A1", "status": "available", "dest": "H1"})
    return out


# ---- MUTATE proposals ----


def propose_dispatch(ambulance_id: str, from_edge: str, rationale: str = "") -> Action:
    return Action(
        tool="emergency.dispatch",
        entity_ids=[ambulance_id, from_edge],
        params={"ambulance_id": ambulance_id, "from_edge": from_edge},
        impact=Impact.MEDIUM,
        rationale=rationale or "dispatch ambulance",
        owner="emergency",
    )


def propose_activate_shelter(shelter_id: str, available: int, rationale: str = "") -> Action:
    return Action(
        tool="emergency.activate_shelter",
        entity_ids=[shelter_id],
        params={"shelter_id": shelter_id, "available": available},
        impact=Impact.MEDIUM,
        rationale=rationale or "activate an emergency shelter",
        owner="emergency",
    )


def propose_set_destination(ambulance_id: str, dest_node: str, rationale: str = "") -> Action:
    return Action(
        tool="emergency.set_destination",
        entity_ids=[ambulance_id, dest_node],
        params={"ambulance_id": ambulance_id, "dest_node": dest_node},
        impact=Impact.LOW,
        rationale=rationale or "redirect ambulance",
        owner="emergency",
    )


__all__ = [
    "ambulance_eta",
    "hospital_access",
    "response_units",
    "propose_dispatch",
    "propose_set_destination",
    "propose_activate_shelter",
]
