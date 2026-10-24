from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..agents.orchestrator import Orchestrator
from ..agents.workflow import Workflow
from ..models import CitySnapshot
from ..services.community import Category, get_community, known_zones, matching_evidence
from ..sim.state import pipeline_affected_edges, pipeline_pressure_classification, preview_pipeline_pressure

router = APIRouter(prefix="/api/community", tags=["community"])


class ComplaintRequest(BaseModel):
    model_config = {"extra": "forbid"}
    zone: str = Field(min_length=1, max_length=128)
    category: Category
    text: str = Field(default="", max_length=2000)
    count: int = Field(default=1, ge=1, le=100, strict=True)
    state: CitySnapshot | None = None


class CommunityPlanRequest(BaseModel):
    model_config = {"extra": "forbid"}
    incident_ids: list[str] = Field(min_length=1, max_length=50)


class PipelinePreviewRequest(BaseModel):
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    asset_id: str = Field(min_length=1, max_length=256)
    pressure_kpa: float = Field(ge=0, le=1000)
    base_state: CitySnapshot | None = None


@router.get("/state")
async def community_state(request: Request) -> dict[str, Any]:
    return get_community(request.app).snapshot()


@router.post("/complaints")
async def complaints(body: ComplaintRequest, request: Request) -> dict[str, Any]:
    community = get_community(request.app)
    if body.zone not in known_zones(community.graph):
        raise HTTPException(status_code=422, detail="zone must belong to the active city")
    return community.submit(zone=body.zone, category=body.category, text=body.text, count=body.count,
                            state=body.state if body.state is not None else community.orchestrator.state,
                            preview=body.state is not None)


@router.post("/pipeline-preview")
async def pipeline_preview(body: PipelinePreviewRequest, request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    asset = next((item for item in graph.infrastructure if item.id == body.asset_id and item.kind == "pipeline"), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="pipeline asset not found in active city")
    base = body.base_state if body.base_state is not None else request.app.state.orchestrator.state
    after = preview_pipeline_pressure(base, graph, asset.id, body.pressure_kpa)
    classification = pipeline_pressure_classification(body.pressure_kpa)
    return {
        "ok": True, "source": "preview", "asset_id": asset.id, "zone": asset.tags.get("zone"),
        "pressure_kpa": body.pressure_kpa, "classification": classification,
        "sensor": {"classification": classification, "pressure_kpa": body.pressure_kpa, "proof_of_leak": False},
        "after_state": after.model_dump(mode="json"),
        "water_failures": after.water_failures,
        "affected_edges": [eid for eid in pipeline_affected_edges(graph, asset.id) if after.flooded_edges.get(eid, 0) > 0],
        "model_note": "What-if hypothesis only: pressure alone does not prove a leak or burst. "
                      "Synthetic thresholds: burst below 20 kPa, probable leak below 150 kPa. "
                      "Road flooding uses explicit affected_edge tags only. Normal pressure does not repair existing failures.",
    }


@router.post("/plan")
async def plan_community(body: CommunityPlanRequest, request: Request) -> dict[str, Any]:
    community = get_community(request.app)
    if community.plan_lock.locked():
        raise HTTPException(status_code=409, detail="community planning is already running")
    async with community.plan_lock:
        live = community.orchestrator
        selected = []
        for incident_id in dict.fromkeys(body.incident_ids):
            record = community.incidents.get(incident_id)
            if record is None:
                raise HTTPException(status_code=404, detail="unknown or expired community incident")
            if record["source"] != "live" or record["status"] != "verified":
                raise HTTPException(status_code=409, detail="only unplanned verified live incidents are eligible")
            incident = record["incident"]
            current = matching_evidence(community.graph, live.state, incident.zone, record["category"])
            if not any(item.dedupe_key == incident.dedupe_key for item in current):
                record["status"] = "stale"
                community.event("stale", incident_id=incident_id)
                raise HTTPException(status_code=409, detail="live evidence changed; submit complaints for fresh verification")
            selected.append(record)

        # Isolate selected verified evidence. The ordinary workflow otherwise plans
        # every open incident, including unrelated ingestion/watch-only entries.
        scoped = Orchestrator(community.graph)
        scoped.state = live.state.model_copy(deep=True)
        before = scoped.state.model_dump()
        scoped.baseline = live.baseline.model_copy(deep=True)
        scoped.incidents = [record["incident"].model_copy(deep=True) for record in selected]
        wf = Workflow(scoped, community.graph)
        community.event("planning", incident_ids=body.incident_ids)
        manager = getattr(request.app.state, "ws_manager", None)
        try:
            plan = await wf.plan(broadcast=manager.broadcast if manager else None)
        except Exception:
            community.event("planning_failed", incident_ids=body.incident_ids)
            raise
        if (request.app.state.graph is not community.graph or request.app.state.orchestrator is not live
                or live.state.model_dump() != before):
            community.event("planning_discarded", reason="live state changed")
            raise HTTPException(status_code=409, detail="live state changed during planning; retry after verification")
        for record in selected:
            # Preserve IDs chosen by the operator even when another source has a
            # similar incident; the completed plan resolves these exact IDs.
            if not any(item.id == record["incident"].id for item in live.incidents):
                live.incidents.append(record["incident"].model_copy(deep=True))
            record["status"] = "planned"
            record["plan_id"] = plan.id
        live.current_plan = plan
        live.plan_history.append(plan)
        live.action_log.extend(scoped.action_log)
        live.plan_started_ts = scoped.plan_started_ts
        live.last_plan_duration_s = scoped.last_plan_duration_s
        community.event("planned", plan_id=plan.id, status=plan.status.value, incident_ids=plan.incident_ids)
        return {"ok": True, "plan": plan.model_dump(mode="json"), "executed": False,
                "requires_approval": plan.status.value == "PENDING_APPROVAL"}
