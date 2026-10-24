from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..models import Action, JointPlan
from ..sim.engine import simulate

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


class WhatIfBody(BaseModel):
    """A simple what-if: a list of hypothetical actions replayed in sim only."""

    actions: list[Action] = Field(default_factory=list)
    label: str = "what-if"


@router.get("")
async def timeline(request: Request) -> dict[str, Any]:
    """Past events, the present snapshot, and the latest verified what-if."""
    orch = request.app.state.orchestrator
    app = request.app
    return {
        "past": orch.timeline[-200:],
        "present": orch.state.model_dump(),
        "baseline": orch.baseline.model_dump(),
        "what_if": app.state.last_what_if,
        "plan_history": [
            {"id": p.id, "status": p.status.value, "version": p.version, "metrics": p.metrics}
            for p in orch.plan_history
        ],
    }


@router.post("/whatif")
async def what_if(body: WhatIfBody, request: Request) -> dict[str, Any]:
    """Run hypothetical actions in the simulator only. Never touches the twin."""
    app = request.app
    orch = app.state.orchestrator
    graph = app.state.graph

    plan = JointPlan(id="whatif", actions=body.actions, incident_ids=[], status="DRAFT")  # type: ignore[arg-type]
    for a in plan.actions:
        if a.owner == "":
            a.owner = "what-if"
    result = simulate(graph, plan, baseline=orch.baseline, start_state=orch.baseline)

    branch = {
        "label": body.label,
        "actions": [a.model_dump() for a in body.actions],
        "result": result.model_dump(),
        "after_state": None,
    }
    # produce the resulting state for the 3D branch rendering (sim-only copy)
    from ..sim.state import apply_action

    st = orch.baseline.model_copy(deep=True)
    for a in body.actions:
        st = apply_action(st, graph, a)
    branch["after_state"] = st.model_dump()

    app.state.last_what_if = branch
    await app.state.ws_manager.broadcast("whatif", {"label": body.label, "passed": result.passed,
                                                    "score": result.score})
    return branch


@router.get("/metrics")
async def compare_metrics(request: Request) -> dict[str, Any]:
    """Before/after comparison: baseline vs current state vs verified plan."""
    orch = request.app.state.orchestrator
    from ..tools.emergency import ambulance_eta

    graph = request.app.state.graph
    base_eta = ambulance_eta(graph, orch.baseline, "A1", "H1")
    now_eta = ambulance_eta(graph, orch.state, "A1", "H1")

    def dark(state) -> int:
        return sum(1 for s in graph.signals if not state.signals_ok.get(s.id, True))

    plan = orch.current_plan
    return {
        "ambulance_eta_baseline_s": base_eta.get("eta_s"),
        "ambulance_eta_now_s": now_eta.get("eta_s"),
        "dark_signals_baseline": dark(orch.baseline),
        "dark_signals_now": dark(orch.state),
        "plan_metrics": plan.metrics if plan else {},
        "sim_notes": plan.critic_feedback if plan else "",
    }
