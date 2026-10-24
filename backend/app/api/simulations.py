from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import Action, JointPlan
from ..sim.engine import simulate
from ..sim.state import initial_state

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


class HazardRequest(BaseModel):
    type: Literal["flood", "close_edge", "power_outage", "signal_dark"]
    edge_id: str | None = None
    depth_cm: float = Field(100.0, ge=0)
    substation_id: str | None = None
    signal_ids: list[str] = Field(default_factory=list)
    label: str = ""


class SimulationRequest(BaseModel):
    label: str = "custom simulation"
    start_from: Literal["healthy", "current"] = "healthy"
    hazards: list[HazardRequest] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)


def _edge_ids(graph) -> set[str]:
    return {edge.id for edge in graph.edges}


def _hazard_action(hazard: HazardRequest, graph) -> Action:
    edge_ids = _edge_ids(graph)
    if hazard.type in {"flood", "close_edge"}:
        if not hazard.edge_id or hazard.edge_id not in edge_ids:
            raise HTTPException(status_code=422, detail=f"Unknown edge_id for {hazard.type}: {hazard.edge_id!r}")
        if hazard.type == "flood":
            return Action(
                tool="traffic.flood_edge",
                entity_ids=[hazard.edge_id],
                params={"edge_id": hazard.edge_id, "depth_cm": hazard.depth_cm},
                impact="HIGH",
                rationale=hazard.label or f"Flood {hazard.edge_id} at {hazard.depth_cm:.0f} cm",
                owner="simulation",
            )
        return Action(
            tool="traffic.close_edge",
            entity_ids=[hazard.edge_id],
            params={"edge_id": hazard.edge_id},
            impact="HIGH",
            rationale=hazard.label or f"Close {hazard.edge_id}",
            owner="simulation",
        )

    if hazard.type == "power_outage":
        known = {sub.id for sub in graph.substations}
        if not hazard.substation_id or hazard.substation_id not in known:
            raise HTTPException(status_code=422, detail=f"Unknown substation_id: {hazard.substation_id!r}")
        return Action(
            tool="power.trip_substation",
            entity_ids=[hazard.substation_id],
            params={"substation_id": hazard.substation_id},
            impact="HIGH",
            rationale=hazard.label or f"Trip {hazard.substation_id}",
            owner="simulation",
        )

    known_signals = {signal.id for signal in graph.signals}
    unknown = sorted(set(hazard.signal_ids) - known_signals)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown signal_ids: {unknown}")
    if not hazard.signal_ids:
        raise HTTPException(status_code=422, detail="signal_ids is required for signal_dark")
    return Action(
        tool="traffic.signal_dark",
        entity_ids=list(hazard.signal_ids),
        params={"signal_ids": list(hazard.signal_ids)},
        impact="MEDIUM",
        rationale=hazard.label or f"Darken {', '.join(hazard.signal_ids)}",
        owner="simulation",
    )


def _explain(graph, hazards: list[HazardRequest], before, after, result) -> tuple[str, list[str], list[str]]:
    blocked = sorted(set(after.flooded_edges) | {eid for eid, closed in after.closed_edges.items() if closed})
    blocked_set = set(blocked)
    affected_nodes: set[str] = set()
    for edge in graph.edges:
        if edge.id in blocked_set:
            affected_nodes.update((edge.src, edge.dst))
    dark_signal_ids = [sid for sid, ok in after.signals_ok.items() if not ok]
    for signal in graph.signals:
        if signal.id in dark_signal_ids:
            affected_nodes.add(signal.node_id)

    explanations: list[str] = []
    for hazard in hazards:
        if hazard.type == "flood":
            explanations.append(f"Flooding on {hazard.edge_id} is modeled at {hazard.depth_cm:.0f} cm and blocks that road segment.")
        elif hazard.type == "close_edge":
            explanations.append(f"Road closure on {hazard.edge_id} removes that segment from route calculations.")
        elif hazard.type == "power_outage":
            explanations.append(f"The outage trips {hazard.substation_id} and darkens signals served by its feeders.")
        else:
            explanations.append(f"The simulation marks {len(hazard.signal_ids)} signal(s) as dark, increasing travel time near them.")

    if blocked:
        explanations.append(f"{len(blocked)} edge(s) are blocked after the hazards and mitigation actions.")
    if dark_signal_ids:
        explanations.append(f"{len(dark_signal_ids)} signal(s) remain offline, so affected roads receive a congestion penalty.")
    if result.notes:
        explanations.extend(result.notes)
    if not explanations:
        explanations.append("No hazards were supplied; the simulator returned the healthy graph baseline.")

    summary = (
        f"Simulation complete: {len(blocked)} blocked edge(s), {len(dark_signal_ids)} dark signal(s), "
        f"and {len(affected_nodes)} affected node(s)."
    )
    return summary, explanations, sorted(affected_nodes)


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    return {
        "city": {"name": graph.name, "source": graph.source, "source_ref": graph.source_ref},
        "hazards": [
            {"type": "flood", "target": "edge_id", "example": graph.edges[0].id if graph.edges else None},
            {"type": "close_edge", "target": "edge_id", "example": graph.edges[0].id if graph.edges else None},
            {"type": "power_outage", "target": "substation_id", "example": graph.substations[0].id if graph.substations else None},
            {"type": "signal_dark", "target": "signal_ids", "example": [graph.signals[0].id] if graph.signals else []},
        ],
        "actions": ["traffic.clear_flood", "traffic.reroute", "power.restore_substation", "emergency.dispatch"],
    }


@router.post("/run")
async def run_simulation(body: SimulationRequest, request: Request) -> dict[str, Any]:
    """Run hazards and optional mitigation actions against the active city graph."""
    app = request.app
    graph = app.state.graph
    orch = app.state.orchestrator
    hazard_actions = [_hazard_action(hazard, graph) for hazard in body.hazards]
    all_actions = hazard_actions + body.actions
    base = orch.state.model_copy(deep=True) if body.start_from == "current" else initial_state(graph)
    plan = JointPlan(id=f"simulation-{body.label.replace(' ', '-').lower()[:36] or 'run'}", actions=all_actions, incident_ids=[], status="DRAFT")  # type: ignore[arg-type]
    result = simulate(graph, plan, baseline=base, start_state=base)
    after = base.model_copy(deep=True)
    if result.final_state:
        from ..models import CitySnapshot

        after = CitySnapshot.model_validate(result.final_state)
    summary, explanations, affected_nodes = _explain(graph, body.hazards, base, after, result)
    response = {
        "ok": True,
        "city": {"name": graph.name, "source": graph.source, "source_ref": graph.source_ref},
        "label": body.label,
        "answer": summary,
        "explanation": explanations,
        "affected_nodes": affected_nodes,
        "hazards": [hazard.model_dump() for hazard in body.hazards],
        "actions": [action.model_dump() for action in body.actions],
        "result": result.model_dump(),
        "before_state": base.model_dump(),
        "after_state": after.model_dump(),
    }
    await app.state.ws_manager.broadcast("simulation_complete", {"label": body.label, "answer": summary})
    return response
