from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/plans", tags=["plans"])


class ApprovalBody(BaseModel):
    plan_id: str
    approver: str = "operator"
    note: str = ""
    approved: bool = True


@router.get("")
async def list_plans(request: Request) -> list[dict[str, Any]]:
    orch = request.app.state.orchestrator
    out = []
    for p in orch.plan_history:
        out.append(
            {
                "id": p.id,
                "status": p.status.value,
                "version": p.version,
                "incident_ids": p.incident_ids,
                "actions": [
                    {"id": a.id, "tool": a.tool, "impact": a.impact.value, "owner": a.owner,
                     "entity_ids": a.entity_ids, "rationale": a.rationale}
                    for a in p.actions
                ],
                "conflicts": [c.model_dump() for c in p.conflicts],
                "resolution": p.resolution,
                "critic_feedback": p.critic_feedback,
                "metrics": p.metrics,
                "proposals": [
                    {"agent": pr.agent, "domain": pr.domain, "summary": pr.summary,
                     "read_calls": pr.read_calls, "actions": len(pr.actions)}
                    for pr in p.proposals
                ],
                "needs_revision": p.needs_revision,
            }
        )
    return out


@router.get("/current")
async def current_plan(request: Request) -> dict[str, Any]:
    orch = request.app.state.orchestrator
    if not orch.current_plan:
        return {}
    p = orch.current_plan
    return {
        "id": p.id,
        "status": p.status.value,
        "version": p.version,
        "actions": [a.model_dump() for a in p.actions],
        "conflicts": [c.model_dump() for c in p.conflicts],
        "resolution": p.resolution,
        "critic_feedback": p.critic_feedback,
        "metrics": p.metrics,
        "proposals": [pr.model_dump() for pr in p.proposals],
        "needs_high_approval": p.status.value == "PENDING_APPROVAL",
    }


@router.post("/approve")
async def approve(body: ApprovalBody, request: Request) -> dict[str, Any]:
    wf = request.app.state.workflow
    mgr = request.app.state.ws_manager
    out = wf.approve(body.plan_id, approver=body.approver, note=body.note, approved=body.approved)
    await mgr.broadcast("approval", {"plan_id": body.plan_id, "approved": body.approved, **out})
    return out


@router.post("/execute")
async def execute(body: ApprovalBody, request: Request) -> dict[str, Any]:
    wf = request.app.state.workflow
    mgr = request.app.state.ws_manager
    out = wf.execute(body.plan_id)
    if out.get("ok"):
        orch = request.app.state.orchestrator
        await mgr.broadcast("state", {"state": orch.state.model_dump()})
        await mgr.broadcast("executed", out)
    return out


@router.get("/action_log")
async def action_log(request: Request) -> list[dict[str, Any]]:
    orch = request.app.state.orchestrator
    return [e.model_dump() for e in orch.action_log]


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, Any]:
    wf = request.app.state.workflow
    return wf.metrics()
