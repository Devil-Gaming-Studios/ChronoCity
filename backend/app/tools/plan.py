from __future__ import annotations

from typing import Any

from ..models import (
    Action,
    AgentProposal,
    CityGraph,
    Conflict,
    Impact,
    JointPlan,
    PlanStatus,
)


def _freeze(value: Any) -> Any:
    """Make nested action parameters safe to use in a deterministic signature."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze(v) for v in value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


class PlanToolbox:
    """The only tools agents use to submit work. Mutating actions are returned
    as data (Action objects) inside a proposal; nothing executes here.

    The orchestrator holds the live state, runs conflict detection, then the
    Critic simulates. Execution happens only after operator approval.
    """

    def __init__(self, graph: CityGraph) -> None:
        self.graph = graph

    def submit_proposal(
        self,
        agent: str,
        domain: str,
        incident_ids: list[str],
        summary: str,
        actions: list[Action],
        read_calls: list[str] | None = None,
    ) -> AgentProposal:
        """READ-then-propose: an agent registers its proposal + which read tools it used."""
        return AgentProposal(
            agent=agent,
            domain=domain,  # type: ignore[arg-type]
            incident_ids=incident_ids,
            summary=summary,
            actions=actions,
            read_calls=read_calls or [],
        )

    def build_joint_plan(self, proposals: list[AgentProposal], incident_ids: list[str]) -> JointPlan:
        actions: list[Action] = []
        seen: set[tuple] = set()
        for p in proposals:
            for a in p.actions:
                sig = (a.tool, tuple(a.entity_ids), _freeze(a.params))
                if sig in seen:  # exact duplicates from overlapping incidents
                    continue
                seen.add(sig)
                actions.append(a)
        plan = JointPlan(
            incident_ids=incident_ids,
            proposals=proposals,
            actions=actions,
            status=PlanStatus.SUBMITTED,
        )
        plan.conflicts = find_conflicts(plan)
        return plan


def find_conflicts(plan: JointPlan) -> list[Conflict]:
    """Deterministic conflict detection over a joint plan's actions.

    Conflict kinds:
      - contradiction: two actions affect the same entity in opposite ways
        (e.g. power.on vs power.off on the same feeder).
      - resource: two actions target the same scarce resource.
      - ordering: a HIGH-impact action that depends on a prior LOW action.
    """
    conflicts: list[Conflict] = []
    by_entity: dict[str, list[Action]] = {}
    for a in plan.actions:
        for e in a.entity_ids:
            by_entity.setdefault(e, []).append(a)

    # contradiction: restore vs trip on same substation/feeder
    opposite_tools = {
        ("power.restore_substation", "power.trip_substation"),
        ("power.reroute_feeder", "power.load_shed"),
        ("traffic.clear_flood", "traffic.flood_edge"),
        ("traffic.close_edge", "traffic.reroute"),
    }
    for entity, acts in by_entity.items():
        for i in range(len(acts)):
            for j in range(i + 1, len(acts)):
                a, b = acts[i], acts[j]
                pair = (a.tool, b.tool)
                if pair in opposite_tools or (pair[1], pair[0]) in opposite_tools:
                    conflicts.append(
                        Conflict(
                            kind="contradiction",
                            a_action_id=a.id,
                            b_action_id=b.id,
                            description=f"{a.owner}({a.tool}) and {b.owner}({b.tool}) contradict on {entity}.",
                        )
                    )

    # resource: multiple agents dispatching the same ambulance / rerouting same edge
    dispatch_by: dict[str, list[Action]] = {}
    for a in plan.actions:
        if a.tool in ("emergency.dispatch", "emergency.set_destination"):
            amb = a.params.get("ambulance_id") or (a.entity_ids[0] if a.entity_ids else "")
            dispatch_by.setdefault(amb, []).append(a)
    for amb, acts in dispatch_by.items():
        owners = {a.owner for a in acts}
        if len(acts) > 1 and len(owners) > 1:
            conflicts.append(
                Conflict(
                    kind="resource",
                    a_action_id=acts[0].id,
                    b_action_id=acts[1].id,
                    description=f"Ambulance {amb} targeted by multiple agents: {', '.join(sorted(owners))}.",
                )
            )

    # ordering: HIGH impact power action concurrent with traffic reroute on same corridor
    high_power = [a for a in plan.actions if a.tool.startswith("power.") and a.impact == Impact.HIGH]
    traffic = [a for a in plan.actions if a.tool.startswith("traffic.")]
    for hp in high_power:
        for t in traffic:
            shared = set(hp.entity_ids) & set(t.entity_ids)
            if shared:
                conflicts.append(
                    Conflict(
                        kind="ordering",
                        a_action_id=hp.id,
                        b_action_id=t.id,
                        description=f"High-impact {hp.tool} must settle before {t.tool} on {sorted(shared)}.",
                    )
                )

    return conflicts


def has_high_impact(plan: JointPlan) -> bool:
    return any(a.impact == Impact.HIGH for a in plan.actions)


__all__ = ["PlanToolbox", "find_conflicts", "has_high_impact"]
