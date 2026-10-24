from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..models import ValidatedSignal
from ..sim.scenarios import combined_incidents, combined_state, flood_readings, trip_readings

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _signals_for(mode: str, graph) -> list[ValidatedSignal]:
    """Pre-reduced signals for each scenario (what the ingest pipeline emits).

    Sensor ids are mapped to city entities so the anomaly detector can build
    concrete incidents: WL_* -> the underpass edge, PWR_S2 -> substation S2.
    """
    if mode == "flood":
        reads = flood_readings(graph)
    elif mode == "trip":
        reads = trip_readings(graph)
    else:
        reads = flood_readings(graph) + trip_readings(graph)

    out: list[ValidatedSignal] = []
    for r in reads:
        if r.kind == "water_level_cm":
            eids = ["E_J4_J6_U1", "U1"]
        elif r.sensor_id.startswith("PWR_"):
            eids = [r.sensor_id.split("_", 1)[1]]  # PWR_S2 -> S2
        else:
            eids = [r.sensor_id]
        out.append(
            ValidatedSignal(
                source="sensor", zone=r.zone, kind=r.kind, value=r.value,
                entity_ids=eids, trust=r.trust, ts=r.ts,
            )
        )
    return out


async def _run(request: Request, mode: str) -> dict[str, Any]:
    """Shared runner: set scenario state -> detect -> plan (streamed) -> return plan."""
    app = request.app
    orch = app.state.orchestrator
    wf = app.state.workflow
    mgr = app.state.ws_manager

    # 1. open the twin in the scenario's failure state (the "before")
    if mode == "flood":
        from ..sim.scenarios import flood_state

        orch.state = flood_state(app.state.graph)
    elif mode == "trip":
        from ..sim.scenarios import trip_state

        orch.state = trip_state(app.state.graph)
    else:
        orch.state = combined_state(app.state.graph)
    orch.incidents.clear()

    await mgr.broadcast("state", {"state": orch.state.model_dump(), "scenario": mode})

    # 2. ingest reduced signals -> incidents (no LLM involved here)
    signals = _signals_for(mode, app.state.graph)
    wf._readings_seen = len(flood_readings(app.state.graph)) + len(trip_readings(app.state.graph))
    new_incidents = wf.detect(signals)
    # for combined, also seed the scripted incident set (deterministic demo)
    if mode == "combined":
        for inc in combined_incidents(app.state.graph):
            orch.add_incident(inc)
    await mgr.broadcast("detected", {"incidents": [i.model_dump() for i in orch.open_incidents()],
                                     "new": len(new_incidents)})

    # 3. run the agent pipeline with WS streaming of each stage
    plan = await wf.plan(broadcast=mgr.broadcast)

    return {
        "ok": True,
        "scenario": mode,
        "incident_count": len(orch.open_incidents()),
        "plan": {
            "id": plan.id,
            "status": plan.status.value,
            "version": plan.version,
            "actions": [a.model_dump() for a in plan.actions],
            "conflicts": [c.model_dump() for c in plan.conflicts],
            "resolution": plan.resolution,
            "critic_feedback": plan.critic_feedback,
            "metrics": plan.metrics,
            "needs_high_approval": plan.status.value == "PENDING_APPROVAL",
        },
        "metrics": wf.metrics(),
    }


@router.post("/combined/start")
async def start_combined(request: Request) -> dict[str, Any]:
    """The demo button: flood + substation trip cascade, end to end."""
    return await _run(request, "combined")


@router.post("/flood/start")
async def start_flood(request: Request) -> dict[str, Any]:
    return await _run(request, "flood")


@router.post("/trip/start")
async def start_trip(request: Request) -> dict[str, Any]:
    return await _run(request, "trip")


@router.post("/reset")
async def reset(request: Request) -> dict[str, Any]:
    """Return the twin to its healthy baseline."""
    from ..sim.state import initial_state

    app = request.app
    orch = app.state.orchestrator
    orch.state = initial_state(app.state.graph)
    orch.incidents.clear()
    orch.current_plan = None
    await app.state.ws_manager.broadcast("state", {"state": orch.state.model_dump(), "scenario": "reset"})
    return {"ok": True}
