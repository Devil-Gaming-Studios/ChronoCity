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


class EditBody(BaseModel):
    plan_id: str
    remove_action_ids: list[str] = []
    note: str = "operator edited response"


class ManualPlanBody(BaseModel):
    label: str = "manual operator response"
    actions: list[dict[str, Any]] = []


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


@router.post("/edit")
async def edit(body: EditBody, request: Request) -> dict[str, Any]:
    wf = request.app.state.workflow
    plan = wf._find_plan(body.plan_id)
    if plan is None:
        return {"ok": False, "error": "plan_not_found"}
    if plan.status.value not in {"PENDING_APPROVAL", "VERIFIED", "REVISED"}:
        return {"ok": False, "error": f"plan in status {plan.status.value}, not editable"}
    removed = set(body.remove_action_ids)
    before = len(plan.actions)
    plan.actions = [action for action in plan.actions if action.id not in removed]
    for proposal in plan.proposals:
        proposal.actions = [action for action in proposal.actions if action.id not in removed]
    plan.proposals = [proposal for proposal in plan.proposals if proposal.actions]
    plan.dropped_action_ids.extend(sorted(removed))
    plan.resolution = f"Operator edited the response: removed {before - len(plan.actions)} action(s)."
    await request.app.state.ws_manager.broadcast("plan_edited", {"plan_id": plan.id, "removed": before - len(plan.actions), "note": body.note})
    return {"ok": True, "plan_id": plan.id, "removed": before - len(plan.actions), "status": plan.status.value}


@router.post("/manual")
async def manual(body: ManualPlanBody, request: Request) -> dict[str, Any]:
    """Manual fallback: create a verified operator plan when agents are unavailable."""
    from ..models import Action, JointPlan
    orch = request.app.state.orchestrator
    actions = [Action.model_validate(item) for item in body.actions]
    plan = JointPlan(id=f"manual-{len(orch.plan_history)+1}", actions=actions, incident_ids=[], status="VERIFIED", resolution="Manual operator fallback plan.")
    orch.current_plan = plan
    orch.plan_history.append(plan)
    await request.app.state.ws_manager.broadcast("manual_plan", {"plan_id": plan.id, "actions": len(actions)})
    return {"ok": True, "plan": {"id": plan.id, "status": plan.status.value, "actions": [action.model_dump() for action in actions]}}


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
