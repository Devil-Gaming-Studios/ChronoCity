from __future__ import annotations

from typing import Any

from ..models import (
    ActionLogEntry,
    ApprovalRecord,
    CityGraph,
    CitySnapshot,
    Incident,
    JointPlan,
    PlanStatus,
)
from ..sim.state import initial_state


class Orchestrator:
    """Holds the live twin state, the open incident queue, and the current plan.

    The workflow (agents/workflow.py) drives it through:
      detect -> negotiate -> verify -> approve -> execute
    """

    def __init__(self, graph: CityGraph) -> None:
        self.graph = graph
        self.state: CitySnapshot = initial_state(graph)
        self.baseline: CitySnapshot = initial_state(graph)
        self.incidents: list[Incident] = []
        self.current_plan: JointPlan | None = None
        self.plan_history: list[JointPlan] = []
        self.action_log: list[ActionLogEntry] = []
        self.approvals: list[ApprovalRecord] = []
        self.timeline: list[dict[str, Any]] = []

    # ---- incident queue ----

    def add_incident(self, inc: Incident) -> bool:
        """Priority + dedupe insert. Returns False if it was a duplicate."""
        if any(i.dedupe_key == inc.dedupe_key and not i.resolved for i in self.incidents):
            return False
        self.incidents.append(inc)
        self.incidents.sort(key=lambda i: i.priority)
        self._emit("incident", {"id": inc.id, "kind": inc.kind, "title": inc.title, "severity": inc.severity.value})
        return True

    def open_incidents(self) -> list[Incident]:
        return [i for i in self.incidents if not i.resolved]

    # ---- action log ----

    def log(self, entry: ActionLogEntry) -> None:
        self.action_log.append(entry)

    # ---- approval gate ----

    def pending_high_impact(self, plan: JointPlan) -> bool:
        return any(a.impact.value == "HIGH" for a in plan.actions)

    def approve(self, plan: JointPlan, approver: str = "operator", note: str = "", approved: bool = True) -> ApprovalRecord:
        rec = ApprovalRecord(plan_id=plan.id, approver=approver, approved=approved, note=note)
        self.approvals.append(rec)
        self.log(
            ActionLogEntry(
                plan_id=plan.id,
                tool="approval",
                phase="approve",
                actor=approver,
                ok=approved,
                detail=note,
            )
        )
        if approved:
            plan.status = PlanStatus.APPROVED
        return rec

    # ---- timeline ----

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        import time

        self.timeline.append({"t": time.time(), "kind": kind, **payload})
        if len(self.timeline) > 500:
            self.timeline = self.timeline[-500:]


__all__ = ["Orchestrator"]
