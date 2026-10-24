from __future__ import annotations

from ..models import JointPlan, PlanStatus, SimulationResult
from ..sim.engine import simulate
from ..models import CityGraph, CitySnapshot
from .llm import get_llm


class Critic:
    """Verify a joint plan by simulating it against the twin.

    Rejects plans that fail (hospital unreachable, travel time worsened, etc.)
    and requests a revision. Deterministic and offline.
    """

    def __init__(self, graph: CityGraph) -> None:
        self.graph = graph
        self.name = "critic"

    def verify(
        self,
        plan: JointPlan,
        baseline: CitySnapshot,
        start_state: CitySnapshot | None = None,
    ) -> SimulationResult:
        result = simulate(self.graph, plan, baseline=baseline, start_state=start_state or baseline)
        if result.passed:
            plan.status = PlanStatus.VERIFIED
            plan.metrics = {
                "score": result.score,
                "travel_time_s": result.travel_time_s,
                "baseline_travel_time_s": result.baseline_travel_time_s,
                "dark_junctions": float(result.dark_junctions),
                "contained_hops": float(result.contained_hops),
            }
            plan.needs_revision = False
            plan.critic_feedback = (
                f"PASS: score={result.score}, eta {result.baseline_travel_time_s:.0f}s -> "
                f"{result.travel_time_s:.0f}s, dark={result.dark_junctions}."
            )
        else:
            plan.status = PlanStatus.REJECTED
            plan.needs_revision = True
            detail = "; ".join(result.notes) if result.notes else "simulation rejected plan."
            plan.critic_feedback = "FAIL: " + detail
        return result

    async def critique_text(self, plan: JointPlan, result: SimulationResult) -> str:
        prompt = (
            f"Critique a verified city-response plan.\n"
            f"Passed={result.passed}, score={result.score}, notes={result.notes}.\n"
            f"Actions={[a.tool for a in plan.actions]}\n"
            f"Give a one-line verdict."
        )
        return await get_llm().complete(self.name, prompt)


def revise_plan(plan: JointPlan, graph: CityGraph, final_state: dict | None = None) -> JointPlan:
    """Revision agent: react to the Critic's rejection deterministically.

    * If signals are still dark after the plan, extend the backfeed to cover
      every remaining dark signal (the usual fix for the combined scenario).
    * Otherwise, drop the flagged action(s) and retry.
    """
    from ..models import CitySnapshot
    from ..tools.power import propose_reroute_feeder

    dropped: list[str] = []

    if final_state is not None:
        st = CitySnapshot(**final_state)
        dark = [sig.id for sig in graph.signals if not st.signals_ok.get(sig.id, True)]
        if dark:
            powered = [f.id for f in graph.feeders if st.powered.get(f.id, True)]
            unpowered = [f.id for f in graph.feeders if not st.powered.get(f.id, True)]
            target = powered[0] if powered else graph.feeders[0].id
            source = unpowered[0] if unpowered else (graph.feeders[-1].id)
            plan.actions.append(
                propose_reroute_feeder(
                    from_feeder=source,
                    to_feeder=target,
                    serves=dark,
                    rationale=f"Revision {plan.version + 1}: backfeed all {len(dark)} residual dark signal(s) from {target}.",
                )
            )
            plan.version += 1
            plan.status = PlanStatus.REVISED
            plan.critic_feedback += (
                f"\nRevision {plan.version}: added backfeed of {', '.join(dark)} from {target}."
            )
            plan.needs_revision = False
            return plan

    # fallback: drop the lowest-value action (last one) and retry
    kept = list(plan.actions)
    if kept:
        dropped.append(kept[-1].id)
        kept = kept[:-1]
    plan.actions = kept
    for p in plan.proposals:
        p.actions = [a for a in p.actions if a.id not in set(dropped)]
    plan.proposals = [p for p in plan.proposals if p.actions]
    plan.version += 1
    plan.status = PlanStatus.REVISED
    plan.critic_feedback += f"\nRevision {plan.version}: dropped {len(dropped)} action(s)."
    plan.needs_revision = False
    return plan


__all__ = ["Critic", "revise_plan"]
