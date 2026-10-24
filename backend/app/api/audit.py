from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/audit", tags=["operator audit"])


@router.get("/pending")
async def pending(request: Request):
    wf = request.app.state.workflow
    items = []
    for saved in request.app.state.audit.current_plans():
        plan = wf._find_plan(saved["id"])
        if plan and plan.status.value in {"VERIFIED", "PENDING_APPROVAL", "APPROVED"}:
            items.append({"plan": saved,
                          "stale": wf.orch.plan_contexts.get(plan.id) != wf.context_fingerprint(plan)})
    return {"items": items}


@router.get("/events")
async def events(request: Request, before: int | None = Query(None, ge=1),
                 limit: int = Query(50, ge=1, le=200), kind: str = "", scope: str = "", plan_id: str = ""):
    return request.app.state.audit.page(before=before, limit=limit, kind=kind, scope=scope, plan_id=plan_id)


@router.get("/plans")
async def plans(request: Request, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    store = request.app.state.audit
    result = store.plans(limit, offset)
    wf = request.app.state.workflow
    for item in result["items"]:
        plan = wf._find_plan(item["plan"]["id"]) if item["runtime_id"] == store.runtime_id else None
        item["actionable"] = bool(plan and plan.status.value in {"VERIFIED", "PENDING_APPROVAL", "APPROVED"})
    return result
