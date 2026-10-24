from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..agents.orchestrator import Orchestrator
from ..agents.workflow import Workflow
from ..models import CitySnapshot
from ..db.audit import record
from ..services.community import Category, ComplaintTargetType, get_community, inferred_complaint_evidence, known_zones, matching_evidence, resolve_complaint_target
from ..sim.state import pipeline_affected_edges, pipeline_pressure_classification, preview_pipeline_pressure

router = APIRouter(prefix="/api/community", tags=["community"])


class ComplaintRequest(BaseModel):
    model_config = {"extra": "forbid"}
    zone: str = Field(default="", max_length=128)
    category: Category
    text: str = Field(default="", max_length=2000)
    count: int = Field(default=1, ge=1, le=100, strict=True)
    state: CitySnapshot | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=256)
    target_type: ComplaintTargetType | None = None


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
    try:
        target = resolve_complaint_target(community.graph, body.target_id, body.target_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    zone = target.get("zone") if target and target.get("zone") else body.zone
    if not zone or zone not in known_zones(community.graph):
        raise HTTPException(status_code=422, detail="zone must belong to the active city")
    result = community.submit(zone=zone, category=body.category, text=body.text, count=body.count,
                            state=body.state if body.state is not None else community.orchestrator.state,
                            preview=body.state is not None, target=target)
    # Live complaint influxes are evidence, not authorization. When the
    # structured simulator evidence verifies a live incident, automatically
    # hand it to the agent workflow so the operator receives a response plan.
    # The workflow still stops at PENDING_APPROVAL; no live action is executed
    # merely because residents submitted complaints.
    agent_action: dict[str, Any] = {"status": "not_started"}
    if body.state is not None:
        agent_action = {"status": "preview_only", "message": "What-if complaints are recorded but do not start live planning."}
    elif result["batch"]["verification_status"] in {"verified", "inferred"}:
        eligible_ids = [item["id"] for item in result["incidents"] if item.get("eligible_for_plan")]
        if not eligible_ids:
            agent_action = {"status": "already_tracked", "message": "The issue is already in the operator workflow."}
        else:
            try:
                planned = await plan_community(CommunityPlanRequest(incident_ids=eligible_ids), request)
                plan = planned.get("plan", {})
                agent_action = {
                    "status": "planned",
                    "plan_id": plan.get("id"),
                    "plan_status": plan.get("status"),
                    "requires_approval": planned.get("requires_approval", True),
                    "actions": [
                        {"tool": action.get("tool"), "entity_ids": action.get("entity_ids", []),
                         "impact": action.get("impact"), "rationale": action.get("rationale", "")}
                        for action in plan.get("actions", [])
                    ],
                    "message": "The AI agent created a response plan for operator approval.",
                }
            except HTTPException as exc:
                agent_action = {"status": "planning_failed", "message": str(exc.detail)}
            except Exception as exc:  # noqa: BLE001
                agent_action = {"status": "planning_failed", "message": f"Agent planning failed: {type(exc).__name__}"}

    result["agent_action"] = agent_action
    result["batch"]["agent_action"] = agent_action
    if agent_action.get("plan_id"):
        result["batch"]["plan_id"] = agent_action["plan_id"]
    record(request.app, "complaint_inflow", result, scope="preview" if body.state is not None else "live",
           actor="citizen", summary=f"{body.count} {body.category} complaints in {body.zone}: "
           f"{result['batch']['verification_status']} → {agent_action['status']}")
    manager = getattr(request.app.state, "ws_manager", None)
    if manager:
        await manager.broadcast("community", {"batch": result["batch"], "agent_action": agent_action})
    return result


@router.post("/pipeline-preview")
async def pipeline_preview(body: PipelinePreviewRequest, request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    asset = next((item for item in graph.infrastructure if item.id == body.asset_id and item.kind == "pipeline"), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="pipeline asset not found in active city")
    base = body.base_state if body.base_state is not None else request.app.state.orchestrator.state
    after = preview_pipeline_pressure(base, graph, asset.id, body.pressure_kpa)
    classification = pipeline_pressure_classification(body.pressure_kpa)
    result = {
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
    record(request.app, "pipeline_preview", {**result, "before_state": base.model_dump(mode="json")},
           scope="preview", actor="operator", summary=f"Pipeline {asset.id}: {body.pressure_kpa} kPa ({classification})")
    return result


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
            if record["source"] != "live" or record["status"] not in {"verified", "inferred"}:
                raise HTTPException(status_code=409, detail="only unplanned verified or complaint-inferred live incidents are eligible")
            incident = record["incident"]
            current = matching_evidence(community.graph, live.state, incident.zone, record["category"])
            if not current and record["status"] == "inferred":
                current = inferred_complaint_evidence(community.graph, incident.zone, record["category"])
            if not any(item.dedupe_key == incident.dedupe_key for item in current):
                record["status"] = "stale"
                community.event("stale", incident_id=incident_id)
                raise HTTPException(status_code=409, detail="live evidence changed; submit complaints for fresh verification")
            selected.append(record)

        # Isolate selected verified evidence. The ordinary workflow otherwise plans
        # every open incident, including unrelated ingestion/watch-only entries.
        scoped = Orchestrator(community.graph, audit=live.audit)
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
        # Complaint-originated plans always receive an explicit operator review,
        # even when their simulated actions are individually below HIGH impact.
        # The complaint channel is evidence, never authorization.
        if plan.status.value == "VERIFIED":
            from ..models import PlanStatus
            plan.status = PlanStatus.PENDING_APPROVAL
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
        live.plan_contexts.update(scoped.plan_contexts)
        live.save_plan(plan, "Verified live complaint response awaiting operator decision")
        live.plan_started_ts = scoped.plan_started_ts
        live.last_plan_duration_s = scoped.last_plan_duration_s
        community.event("planned", plan_id=plan.id, status=plan.status.value, incident_ids=plan.incident_ids)
        return {"ok": True, "plan": plan.model_dump(mode="json"), "executed": False,
                "requires_approval": plan.status.value == "PENDING_APPROVAL"}
