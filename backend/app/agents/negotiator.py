from __future__ import annotations

from ..models import Conflict, JointPlan, PlanStatus
from .llm import get_llm


# fixed priority order for deterministic resolution
DOMAIN_PRIORITY = ["emergency", "power", "traffic"]


class Negotiator:
    """Resolve conflicts in a joint plan with a deterministic priority order.

    Conflicts are found by tools.plan.find_conflicts. For each, we keep the
    action owned by the higher-priority domain and drop/adjust the loser.
    The natural-language resolution is generated via the LLM (scripted offline).
    """

    def __init__(self) -> None:
        self.name = "negotiator"

    def resolve(self, plan: JointPlan) -> JointPlan:
        if not plan.conflicts:
            if not plan.resolution:
                plan.resolution = "No conflicts; joint plan accepted as-is."
            return plan

        action_owner = {a.id: a for a in plan.actions}
        drop_ids: set[str] = set()
        notes: list[str] = []

        for c in plan.conflicts:
            a = action_owner.get(c.a_action_id)
            b = action_owner.get(c.b_action_id)
            if not a or not b:
                continue
            pa = DOMAIN_PRIORITY.index(a.owner) if a.owner in DOMAIN_PRIORITY else len(DOMAIN_PRIORITY)
            pb = DOMAIN_PRIORITY.index(b.owner) if b.owner in DOMAIN_PRIORITY else len(DOMAIN_PRIORITY)
            # lower index == higher priority == wins
            if c.kind in ("contradiction", "resource"):
                loser = b if pb > pa else a
                drop_ids.add(loser.id)
                notes.append(
                    f"{c.kind}: {a.owner}({a.tool}) beats {b.owner}({b.tool}); dropped {loser.tool}."
                )
            elif c.kind == "ordering":
                # keep both but annotate: high-impact action runs first
                notes.append(f"ordering: {a.tool} executes before {b.tool}.")

        kept = [a for a in plan.actions if a.id not in drop_ids]
        dropped = [a for a in plan.actions if a.id in drop_ids]
        plan.actions = kept
        # remove proposals that now have no actions
        for p in plan.proposals:
            p.actions = [a for a in p.actions if a.id not in drop_ids]
        plan.proposals = [p for p in plan.proposals if p.actions]

        plan.resolution = " | ".join(notes) if notes else "Resolved."
        plan.dropped_action_ids = [a.id for a in dropped]  # type: ignore[attr-defined]
        plan.status = PlanStatus.REVISED if dropped else PlanStatus.SUBMITTED
        return plan

    async def summarize(self, plan: JointPlan) -> str:
        prompt = (
            f"Resolve conflicts in a city-response joint plan.\n"
            f"Conflicts: {[c.description for c in plan.conflicts]}\n"
            f"Resolution: {plan.resolution}\n"
            f"Summarize the agreed joint plan in one sentence."
        )
        return await get_llm().complete(self.name, prompt)


__all__ = ["Negotiator"]
