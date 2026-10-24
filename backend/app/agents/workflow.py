from __future__ import annotations

from typing import Any, Callable, Awaitable

from ..models import (
    ActionLogEntry,
    AgentProposal,
    CityGraph,
    Incident,
    Impact,
    JointPlan,
    PlanStatus,
    ValidatedSignal,
)
from ..tools.plan import PlanToolbox, find_conflicts, has_high_impact
from .critic import Critic, revise_plan
from .llm import get_llm
from .negotiator import Negotiator
from .orchestrator import Orchestrator
from .specialists import EmergencyAgent, PowerAgent, TrafficAgent


Broadcast = Callable[[str, dict[str, Any]], Awaitable[None]]


class Workflow:
    """The agent pipeline: specialists propose, the Negotiator reconciles,
    the Critic verifies in simulation, a human approves HIGH-impact actions,
    and only then are actions executed against the twin.

    Google ADK note: the same structure maps onto ADK's SequentialAgent /
    ParallelAgent (specialists) / LoopAgent (critic-revise loop). We keep ADK
    optional so the demo runs offline; see _adk_note() below.
    """

    def __init__(self, orch: Orchestrator, graph: CityGraph) -> None:
        self.orch = orch
        self.graph = graph
        self.toolbox = PlanToolbox(graph)
        self.negotiator = Negotiator()
        self.critic = Critic(graph)
        self.specialists = [PowerAgent(graph), TrafficAgent(graph), EmergencyAgent(graph)]
        self.revision_limit = 3

    # ------------------------------------------------ stage 1: detect

    def detect(self, signals: list[ValidatedSignal]) -> list[Incident]:
        """Reduced signals -> incidents (the ingest layer does the reduction)."""
        from ..ingest.aggregator import Aggregator
        from ..ingest.anomaly import AnomalyDetector

        agg = Aggregator(window_seconds=0.0)
        det = AnomalyDetector(self.graph)
        new: list[Incident] = []
        for s in signals:
            agg.add(s)
        for summary in agg.flush():
            for inc in det.detect(summary):
                if self.orch.add_incident(inc):
                    new.append(inc)
        return new

    # ------------------------------------------------ stage 2: plan (parallel specialists)

    async def plan(self, broadcast: Broadcast | None = None) -> JointPlan:
        import time
        self.orch.plan_started_ts = time.time()
        incidents = self.orch.open_incidents()
        incident_ids = [i.id for i in incidents]
        llm = get_llm()
        llm.reset_budget()

        if broadcast:
            await broadcast("stage", {"stage": "plan", "agents": [s.name for s in self.specialists]})

        # specialists run concurrently (parallel agent semantics)
        import asyncio

        proposals: list[AgentProposal] = await asyncio.gather(
            *(s.run(self.orch.state, incidents) for s in self.specialists)
        )
        proposals = [p for p in proposals if p.actions]
        for p in proposals:
            self.orch.log(
                ActionLogEntry(
                    plan_id="pending",
                    tool=f"{p.domain}.propose",
                    phase="propose",
                    actor=p.agent,
                    detail=f"{len(p.actions)} actions after {len(p.read_calls)} reads",
                )
            )
            for read_call in p.read_calls:
                self.orch.log(ActionLogEntry(plan_id="pending", tool=read_call, phase="propose", actor=p.agent, detail="read tool call", impact="LOW"))

        plan = self.toolbox.build_joint_plan(proposals, incident_ids)
        if broadcast:
            await broadcast("plan", {"plan_id": plan.id, "actions": len(plan.actions), "conflicts": len(plan.conflicts)})

        # ------------------------------------------------ stage 3: negotiate
        plan = self.negotiator.resolve(plan)
        self.orch.log(
            ActionLogEntry(plan_id=plan.id, tool="negotiator.resolve", phase="propose", actor="negotiator",
                           ok=True, detail=plan.resolution)
        )
        if broadcast:
            await broadcast("negotiate", {"plan_id": plan.id, "conflicts": len(plan.conflicts), "resolution": plan.resolution})

        # ------------------------------------------------ stage 4: verify (critic loop)
        iteration = 0
        result = self.critic.verify(plan, baseline=self.orch.baseline, start_state=self.orch.state)
        if broadcast:
            await broadcast("critic", {
                "plan_id": plan.id, "iteration": iteration,
                "passed": result.passed, "feedback": plan.critic_feedback,
                "version": plan.version,
            })
        while plan.needs_revision and iteration < self.revision_limit:
            iteration += 1
            plan = revise_plan(plan, self.graph, final_state=result.final_state)
            plan.conflicts = find_conflicts(plan)
            plan = self.negotiator.resolve(plan)
            result = self.critic.verify(plan, baseline=self.orch.baseline, start_state=self.orch.state)
            if broadcast:
                await broadcast("critic", {
                    "plan_id": plan.id, "iteration": iteration,
                    "passed": result.passed, "feedback": plan.critic_feedback,
                    "version": plan.version,
                })

        self.orch.log(
            ActionLogEntry(plan_id=plan.id, tool="critic.verify", phase="verify", actor="critic",
                           ok=result.passed, detail=plan.critic_feedback)
        )

        if result.passed and has_high_impact(plan):
            plan.status = PlanStatus.PENDING_APPROVAL
        elif result.passed:
            plan.status = PlanStatus.VERIFIED

        self.orch.current_plan = plan
        self.orch.plan_history.append(plan)
        self.orch.last_plan_duration_s = time.time() - (self.orch.plan_started_ts or time.time())
        plan.metrics["time_to_plan_s"] = round(self.orch.last_plan_duration_s, 3)
        if broadcast:
            await broadcast("verified", {
                "plan_id": plan.id, "passed": result.passed, "status": plan.status.value,
                "metrics": plan.metrics, "needs_high_approval": has_high_impact(plan) and result.passed,
            })
        return plan

    # ------------------------------------------------ stage 5: approval

    def approve(self, plan_id: str, approver: str = "operator", note: str = "", approved: bool = True) -> dict[str, Any]:
        plan = self._find_plan(plan_id)
        if plan is None:
            return {"ok": False, "error": "plan_not_found"}
        if plan.status not in (PlanStatus.PENDING_APPROVAL, PlanStatus.VERIFIED):
            return {"ok": False, "error": f"plan in status {plan.status.value}, not approvable"}
        rec = self.orch.approve(plan, approver=approver, note=note, approved=approved)
        if not approved:
            plan.status = PlanStatus.FAILED
            return {"ok": True, "approved": False, "plan_id": plan.id}
        if plan.status != PlanStatus.APPROVED:
            plan.status = PlanStatus.APPROVED
        return {"ok": True, "approved": True, "plan_id": plan.id, "approval_id": rec.id}

    # ------------------------------------------------ stage 6: execute

    def execute(self, plan_id: str) -> dict[str, Any]:
        """Apply an APPROVED plan to the live twin. Never runs unapproved HIGH actions."""
        from ..sim.state import apply_action

        plan = self._find_plan(plan_id)
        if plan is None:
            return {"ok": False, "error": "plan_not_found"}

        if plan.status != PlanStatus.APPROVED:
            # guard: HIGH-impact plan that skipped approval is refused
            if has_high_impact(plan):
                self.orch.log(ActionLogEntry(plan_id=plan.id, tool="execute", phase="approve",
                                             actor="system", ok=False, detail="HIGH-impact without approval"))
                return {"ok": False, "error": "approval_required"}
            plan.status = PlanStatus.APPROVED

        executed = 0
        for a in plan.actions:
            self.orch.state = apply_action(self.orch.state, self.graph, a)
            self.orch.log(
                ActionLogEntry(
                    plan_id=plan.id, action_id=a.id, tool=a.tool, phase="execute",
                    actor=a.owner, impact=a.impact, ok=True, detail=a.rationale,
                )
            )
            executed += 1

        plan.status = PlanStatus.EXECUTED
        # resolve the incidents this plan addressed
        for inc in self.orch.incidents:
            if inc.id in plan.incident_ids:
                inc.resolved = True
        self.orch._emit("executed", {"plan_id": plan.id, "actions": executed, "status": plan.status.value})
        return {"ok": True, "executed": executed, "plan_id": plan.id}

    # ------------------------------------------------ helpers

    def _find_plan(self, plan_id: str) -> JointPlan | None:
        if self.orch.current_plan and self.orch.current_plan.id == plan_id:
            return self.orch.current_plan
        for p in self.orch.plan_history:
            if p.id == plan_id:
                return p
        return None

    def metrics(self) -> dict[str, Any]:
        """Demo metrics: LLM calls vs data processed, verification stats."""
        llm = get_llm().stats()
        readings = len(self.orch.timeline)  # placeholder; real counter below
        return {
            "llm_calls": llm["calls_used"],
            "llm_budget": llm["budget"],
            "llm_mode": llm["mode"],
            "incidents": len(self.orch.incidents),
            "plans": len(self.orch.plan_history),
            "plans_verified": sum(1 for p in self.orch.plan_history if p.status in (PlanStatus.VERIFIED, PlanStatus.APPROVED, PlanStatus.EXECUTED)),
            "plans_rejected": sum(1 for p in self.orch.plan_history if p.status == PlanStatus.REJECTED),
            "approvals": len(self.orch.approvals),
            "actions_executed": sum(1 for e in self.orch.action_log if e.phase == "execute"),
            "readings_processed": getattr(self, "_readings_seen", readings),
            "time_to_plan_s": self.orch.last_plan_duration_s,
            "watch_alerts": len(self.orch.watch_alerts),
        }


def adk_available() -> bool:
    try:
        import google.adk  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


__all__ = ["Workflow", "adk_available"]
