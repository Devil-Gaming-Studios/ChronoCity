from __future__ import annotations

from app.agents.critic import revise_plan
from app.agents.negotiator import Negotiator
from app.models import Action, AgentProposal, Impact, JointPlan, PlanStatus
from app.tools.plan import PlanToolbox, find_conflicts, has_high_impact


def _combined_proposals(graph):
    """Power sheds/backfeeds, Traffic closes + reroutes the same edge (seeded conflict)."""
    power = AgentProposal(
        agent="power_agent",
        domain="power",
        summary="Backfeed and shed.",
        actions=[
            Action(tool="power.reroute_feeder", entity_ids=["S2", "F1"],
                   params={"from_feeder": "S2", "to_feeder": "F1", "serves": ["SIG_J5"]},
                   impact=Impact.HIGH, owner="power"),
            Action(tool="power.load_shed", entity_ids=["S1"],
                   params={"substation_id": "S1", "feeders": ["F2"]},
                   impact=Impact.MEDIUM, owner="power"),
        ],
        read_calls=["power.substation_status(S2)"],
    )
    traffic = AgentProposal(
        agent="traffic_agent",
        domain="traffic",
        summary="Close + reroute flooded edge.",
        actions=[
            Action(tool="traffic.close_edge", entity_ids=["E_J4_J6_U1"],
                   params={"edge_id": "E_J4_J6_U1"}, impact=Impact.MEDIUM, owner="traffic"),
            Action(tool="traffic.reroute", entity_ids=["E_J4_J6_U1", "E_J5_J7"],
                   params={"slow_edge_id": "E_J4_J6_U1", "fast_edge_id": "E_J5_J7", "factor": 2.0},
                   impact=Impact.LOW, owner="traffic"),
        ],
        read_calls=["traffic.edge_status(E_J4_J6_U1)"],
    )
    emergency = AgentProposal(
        agent="emergency_agent",
        domain="emergency",
        summary="Dispatch A1.",
        actions=[
            Action(tool="emergency.dispatch", entity_ids=["A1", "E_DEPOT_J1"],
                   params={"ambulance_id": "A1", "from_edge": "E_DEPOT_J1"},
                   impact=Impact.MEDIUM, owner="emergency"),
        ],
        read_calls=["emergency.ambulance_eta(A1->H1)"],
    )
    return [power, traffic, emergency]


def test_seeded_conflict_detected(graph):
    box = PlanToolbox(graph)
    plan = box.build_joint_plan(_combined_proposals(graph), ["i1"])
    assert len(plan.conflicts) >= 1
    kinds = {c.kind for c in plan.conflicts}
    assert "contradiction" in kinds  # close_edge vs reroute on the same edge
    assert has_high_impact(plan)


def test_negotiator_resolves_deterministically(graph):
    box = PlanToolbox(graph)
    plan = box.build_joint_plan(_combined_proposals(graph), ["i1"])
    n = Negotiator()
    resolved = n.resolve(plan)
    assert resolved.resolution and "contradiction" in resolved.resolution
    # the contradiction loser was dropped, plan actions reduced
    assert len(resolved.actions) < len(plan.actions) or "ordering" in resolved.resolution
    # deterministic: same input -> same outcome
    plan2 = box.build_joint_plan(_combined_proposals(graph), ["i1"])
    resolved2 = Negotiator().resolve(plan2)
    assert [a.tool for a in resolved.actions] == [a.tool for a in resolved2.actions]


def test_revise_adds_backfeed_for_residual_dark(graph, combined):
    from app.sim.engine import simulate

    # empty plan -> final_state has dark signals
    plan = JointPlan(id="p", actions=[], status=PlanStatus.REJECTED, needs_revision=True)
    res = simulate(graph, plan, start_state=combined)
    assert res.passed is False
    revised = revise_plan(graph=graph, plan=plan, final_state=res.final_state)
    assert revised.version == 2
    assert any(a.tool == "power.reroute_feeder" for a in revised.actions)
    # the revised plan now passes
    res2 = simulate(graph, revised, start_state=combined)
    assert res2.passed is True
    assert res2.dark_junctions == 0
