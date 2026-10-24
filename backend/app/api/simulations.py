from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import Action, JointPlan
from ..sim.engine import run_ticks, simulate
from ..sim.state import initial_state

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


class HazardRequest(BaseModel):
    type: Literal[
        "rain", "flood", "close_edge", "heavy_traffic", "power_outage", "power_overload",
        "power_wire_break", "water_pipe_break", "water_pressure", "signal_dark"
    ]
    edge_id: str | None = None
    asset_id: str | None = None
    depth_cm: float = Field(100.0, ge=0)
    congestion_factor: float = Field(2.0, ge=1.0, le=10.0)
    rain_mm: float = Field(0.0, ge=0)
    duration_min: float = Field(30.0, ge=0)
    load_mw: float = Field(0.0, ge=0)
    pressure_kpa: float = Field(350.0, ge=0)
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


def _hazard_actions(hazard: HazardRequest, graph) -> list[Action]:
    edge_ids = {edge.id for edge in graph.edges}
    asset_by_id = {asset.id: asset for asset in graph.infrastructure}

    if hazard.type == "rain":
        underpass_edges = [edge.edge_id for edge in graph.underpasses]
        if not underpass_edges:
            underpass_edges = [
                edge.id for edge in graph.edges
                if edge.kind == "underpass" or edge.tags.get("tunnel") in {"yes", "true", "1"}
            ]
        if not underpass_edges:
            raise HTTPException(status_code=422, detail="No mapped underpass or flood-prone edge exists in this city")
        depth = max(10.0, hazard.rain_mm * 0.8)
        return [
            Action(
                tool="traffic.flood_edge",
                entity_ids=[edge_id],
                params={"edge_id": edge_id, "depth_cm": depth, "rain_mm": hazard.rain_mm, "duration_min": hazard.duration_min},
                impact="HIGH",
                rationale=hazard.label or f"Rainfall {hazard.rain_mm:.0f} mm over {hazard.duration_min:.0f} minutes",
                owner="simulation",
            )
            for edge_id in underpass_edges
        ]

    if hazard.type == "heavy_traffic":
        if not hazard.edge_id or hazard.edge_id not in edge_ids:
            raise HTTPException(status_code=422, detail=f"Unknown edge_id for heavy_traffic: {hazard.edge_id!r}")
        return [Action(
            tool="traffic.set_congestion",
            entity_ids=[hazard.edge_id],
            params={"edge_id": hazard.edge_id, "factor": hazard.congestion_factor},
            impact="MEDIUM",
            rationale=hazard.label or f"Heavy traffic on {hazard.edge_id}",
            owner="simulation",
        )]

    if hazard.type in {"flood", "close_edge"}:
        if not hazard.edge_id or hazard.edge_id not in edge_ids:
            raise HTTPException(status_code=422, detail=f"Unknown edge_id for {hazard.type}: {hazard.edge_id!r}")
        if hazard.type == "flood":
            return [Action(tool="traffic.flood_edge", entity_ids=[hazard.edge_id], params={"edge_id": hazard.edge_id, "depth_cm": hazard.depth_cm}, impact="HIGH", rationale=hazard.label or f"Flood {hazard.edge_id} at {hazard.depth_cm:.0f} cm", owner="simulation")]
        return [Action(tool="traffic.close_edge", entity_ids=[hazard.edge_id], params={"edge_id": hazard.edge_id}, impact="HIGH", rationale=hazard.label or f"Close {hazard.edge_id}", owner="simulation")]

    if hazard.type in {"power_outage", "power_overload"}:
        known = {sub.id for sub in graph.substations}
        if not hazard.substation_id or hazard.substation_id not in known:
            raise HTTPException(status_code=422, detail=f"Unknown substation_id: {hazard.substation_id!r}")
        if hazard.type == "power_outage":
            return [Action(tool="power.trip_substation", entity_ids=[hazard.substation_id], params={"substation_id": hazard.substation_id}, impact="HIGH", rationale=hazard.label or f"Trip {hazard.substation_id}", owner="simulation")]
        return [Action(tool="power.set_load", entity_ids=[hazard.substation_id], params={"substation_id": hazard.substation_id, "load_mw": hazard.load_mw}, impact="HIGH", rationale=hazard.label or f"Set {hazard.substation_id} load to {hazard.load_mw:.1f} MW", owner="simulation")]

    if hazard.type in {"power_wire_break", "water_pipe_break", "water_pressure"}:
        if not hazard.asset_id or hazard.asset_id not in asset_by_id:
            raise HTTPException(status_code=422, detail=f"Unknown infrastructure asset_id: {hazard.asset_id!r}")
        asset = asset_by_id[hazard.asset_id]
        if hazard.type == "power_wire_break" and asset.kind != "power_line":
            raise HTTPException(status_code=422, detail=f"Asset {hazard.asset_id} is not a mapped power line")
        if hazard.type in {"water_pipe_break", "water_pressure"} and asset.kind not in {"pipeline", "water_works", "wastewater_plant", "waterway"}:
            raise HTTPException(status_code=422, detail=f"Asset {hazard.asset_id} is not a mapped water asset")
        if hazard.type == "power_wire_break":
            return [Action(tool="power.break_line", entity_ids=[hazard.asset_id], params={"asset_id": hazard.asset_id}, impact="HIGH", rationale=hazard.label or f"Break power line {hazard.asset_id}", owner="simulation")]
        if hazard.type == "water_pipe_break":
            return [Action(tool="water.break_pipe", entity_ids=[hazard.asset_id], params={"asset_id": hazard.asset_id}, impact="HIGH", rationale=hazard.label or f"Break water asset {hazard.asset_id}", owner="simulation")]
        return [Action(tool="water.set_pressure", entity_ids=[hazard.asset_id], params={"asset_id": hazard.asset_id, "pressure_kpa": hazard.pressure_kpa}, impact="MEDIUM", rationale=hazard.label or f"Set water pressure on {hazard.asset_id} to {hazard.pressure_kpa:.0f} kPa", owner="simulation")]

    known_signals = {signal.id for signal in graph.signals}
    unknown = sorted(set(hazard.signal_ids) - known_signals)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown signal_ids: {unknown}")
    if not hazard.signal_ids:
        raise HTTPException(status_code=422, detail="signal_ids is required for signal_dark")
    return [Action(tool="traffic.signal_dark", entity_ids=list(hazard.signal_ids), params={"signal_ids": list(hazard.signal_ids)}, impact="MEDIUM", rationale=hazard.label or f"Darken {', '.join(hazard.signal_ids)}", owner="simulation")]

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
        if hazard.type == "rain":
            explanations.append(f"Rainfall of {hazard.rain_mm:.0f} mm over {hazard.duration_min:.0f} minutes is applied to mapped flood-prone edges.")
        elif hazard.type == "flood":
            explanations.append(f"Flooding on {hazard.edge_id} is modeled at {hazard.depth_cm:.0f} cm and blocks that road segment.")
        elif hazard.type == "close_edge":
            explanations.append(f"Road closure on {hazard.edge_id} removes that segment from route calculations.")
        elif hazard.type == "heavy_traffic":
            explanations.append(f"Traffic on {hazard.edge_id} is modeled as heavy, increasing its travel time by {hazard.congestion_factor:.1f}×.")
        elif hazard.type == "power_outage":
            explanations.append(f"The outage trips {hazard.substation_id} and darkens signals served by its feeders.")
        elif hazard.type == "power_overload":
            explanations.append(f"The load on {hazard.substation_id} is set to {hazard.load_mw:.1f} MW; exceeding capacity trips the station.")
        elif hazard.type == "power_wire_break":
            explanations.append(f"The power-line asset {hazard.asset_id} is marked failed for grid diagnostics.")
        elif hazard.type == "water_pipe_break":
            explanations.append(f"The water asset {hazard.asset_id} is marked as a pipe break and its pressure is set to zero.")
        elif hazard.type == "water_pressure":
            explanations.append(f"Water pressure on {hazard.asset_id} is modeled at {hazard.pressure_kpa:.0f} kPa.")
        else:
            explanations.append(f"The simulation marks {len(hazard.signal_ids)} signal(s) as dark, increasing travel time near them.")

    if blocked:
        explanations.append(f"{len(blocked)} edge(s) are blocked after the hazards and mitigation actions.")
    if dark_signal_ids:
        explanations.append(f"{len(dark_signal_ids)} signal(s) remain offline, so affected roads receive a congestion penalty.")
    failed_assets = sorted(set(after.failed_assets) | set(after.water_failures))
    if failed_assets:
        explanations.append(f"{len(failed_assets)} infrastructure asset(s) are failed or degraded: {', '.join(failed_assets)}.")
    if result.notes:
        explanations.extend(result.notes)
    if not explanations:
        explanations.append("No hazards were supplied; the simulator returned the healthy graph baseline.")

    summary = (
        f"Simulation complete: {len(blocked)} blocked edge(s), {len(dark_signal_ids)} dark signal(s), "
        f"{len(failed_assets)} failed asset(s), and {len(affected_nodes)} affected node(s)."
    )
    return summary, explanations, sorted(affected_nodes)


class TickRequest(BaseModel):
    ticks: int = Field(1, ge=1, le=3600)
    seconds_per_tick: float = Field(1.0, gt=0, le=60)
    start_from: Literal["healthy", "current"] = "current"


@router.post("/tick")
async def tick(body: TickRequest, request: Request) -> dict[str, Any]:
    """Advance the live twin clock through deterministic discrete-event ticks."""
    app = request.app
    graph = app.state.graph
    orch = app.state.orchestrator
    base = orch.state.model_copy(deep=True) if body.start_from == "current" else initial_state(graph)
    after = run_ticks(graph, base, body.ticks, body.seconds_per_tick)
    orch.state = after
    await app.state.ws_manager.broadcast("state_delta", {"state": after.model_dump(), "ticks": body.ticks})
    return {"ok": True, "ticks": body.ticks, "seconds_per_tick": body.seconds_per_tick, "before_state": base.model_dump(), "after_state": after.model_dump()}


@router.post("/fork")
async def fork(body: SimulationRequest, request: Request) -> dict[str, Any]:
    """Return a simulation branch from a snapshot without changing live state."""
    body = body.model_copy(update={"start_from": "current"})
    response = await run_simulation(body, request)
    response["live_state_unchanged"] = True
    return response


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    return {
        "city": {"name": graph.name, "source": graph.source, "source_ref": graph.source_ref},
        "hazards": [
            {"type": "rain", "target": "rain_mm", "example": 120},
            {"type": "flood", "target": "edge_id", "example": graph.edges[0].id if graph.edges else None},
            {"type": "close_edge", "target": "edge_id", "example": graph.edges[0].id if graph.edges else None},
            {"type": "heavy_traffic", "target": "edge_id + congestion_factor", "example": graph.edges[0].id if graph.edges else None},
            {"type": "power_outage", "target": "substation_id", "example": graph.substations[0].id if graph.substations else None},
            {"type": "power_overload", "target": "substation_id + load_mw", "example": graph.substations[0].id if graph.substations else None},
            {"type": "power_wire_break", "target": "asset_id", "example": next((a.id for a in graph.infrastructure if a.kind == "power_line"), None)},
            {"type": "water_pipe_break", "target": "asset_id", "example": next((a.id for a in graph.infrastructure if a.kind in {"pipeline", "waterway", "water_works"}), None)},
            {"type": "signal_dark", "target": "signal_ids", "example": [graph.signals[0].id] if graph.signals else []},
        ],
        "actions": ["traffic.clear_flood", "traffic.reroute", "power.restore_substation", "power.set_load", "power.break_line", "water.break_pipe", "traffic.set_congestion", "emergency.dispatch"],
    }


@router.post("/run")
async def run_simulation(body: SimulationRequest, request: Request) -> dict[str, Any]:
    """Run hazards and optional mitigation actions against the active city graph."""
    app = request.app
    graph = app.state.graph
    orch = app.state.orchestrator
    hazard_actions = [action for hazard in body.hazards for action in _hazard_actions(hazard, graph)]
    all_actions = hazard_actions + body.actions
    base = orch.state.model_copy(deep=True) if body.start_from == "current" else initial_state(graph)
    plan = JointPlan(id=f"simulation-{body.label.replace(' ', '-').lower()[:36] or 'run'}", actions=all_actions, incident_ids=[], status="DRAFT")  # type: ignore[arg-type]
    result = simulate(graph, plan, baseline=base, start_state=base)
    after = base.model_copy(deep=True)
    if result.final_state:
        from ..models import CitySnapshot

        after = CitySnapshot.model_validate(result.final_state)
    summary, explanations, affected_nodes = _explain(graph, body.hazards, base, after, result)
    affected_assets = sorted(set(after.failed_assets) | set(after.water_failures))
    response = {
        "ok": True,
        "city": {"name": graph.name, "source": graph.source, "source_ref": graph.source_ref},
        "label": body.label,
        "answer": summary,
        "explanation": explanations,
        "affected_nodes": affected_nodes,
        "affected_assets": affected_assets,
        "hazards": [hazard.model_dump() for hazard in body.hazards],
        "actions": [action.model_dump() for action in body.actions],
        "result": result.model_dump(),
        "before_state": base.model_dump(),
        "after_state": after.model_dump(),
    }
    await app.state.ws_manager.broadcast("simulation_complete", {"label": body.label, "answer": summary})
    return response
