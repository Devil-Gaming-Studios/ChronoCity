from __future__ import annotations

from app.models import Action, JointPlan, PlanStatus
from app.sim.engine import simulate
from app.sim.state import apply_action, reachable_travel_time


def _eta(state, graph, src="DEPOT", dst="H1") -> float:
    return reachable_travel_time(state, graph, src, dst)


def test_healthy_route_exists(graph, healthy):
    tt = _eta(healthy, graph)
    assert tt < 200  # seconds, free-flow


def test_flood_blocks_underpass_and_slows(graph, flooded, healthy):
    assert flooded.flooded_edges.get("E_J4_J6_U1") == 140
    assert flooded.edge_travel_s["E_J4_J6_U1"] >= 9999
    assert _eta(flooded, graph) > _eta(healthy, graph)


def test_trip_darkens_signals(graph, tripped):
    dark = [s.id for s in graph.signals if not tripped.signals_ok.get(s.id, True)]
    assert set(dark) == {"SIG_J5", "SIG_J6", "SIG_J7", "SIG_J8", "SIG_N7"}
    assert tripped.powered["F3"] is False and tripped.powered["F4"] is False
    # dark junctions slow crossing traffic
    assert tripped.edge_travel_s["E_J5_J7"] > 30


def test_combined_state_has_both_failures(combined):
    assert "E_J4_J6_U1" in combined.flooded_edges
    assert combined.powered["F3"] is False and combined.powered["F4"] is False
    assert any(not v for v in combined.signals_ok.values())


def test_apply_action_is_pure(graph, healthy):
    snap = healthy.model_copy(deep=True)
    a = Action(tool="power.trip_substation", entity_ids=["S2"], params={"substation_id": "S2"})
    out = apply_action(healthy, graph, a)
    assert out is not healthy
    assert healthy == snap  # input untouched


def test_simulate_does_not_mutate_start_state(graph, combined):
    plan = JointPlan(id="p1", actions=[], status=PlanStatus.SUBMITTED)
    before = combined.model_copy(deep=True)
    res = simulate(graph, plan, start_state=combined)
    assert combined == before
    # empty plan leaves dark junctions -> must fail
    assert res.passed is False
    assert res.dark_junctions > 0


def test_backfeed_restores_and_passes(graph, combined):
    from app.tools.power import propose_reroute_feeder

    dark = [s.id for s in graph.signals if not combined.signals_ok.get(s.id, True)]
    action = propose_reroute_feeder(from_feeder="F3", to_feeder="F1", serves=dark)
    # shed F2 is also dark; include every dark signal
    plan = JointPlan(id="p2", actions=[action], status=PlanStatus.SUBMITTED)
    res = simulate(graph, plan, start_state=combined)
    # the backfeed targets F1 (healthy) -> all listed signals turn on
    assert res.dark_junctions == 0
    assert res.passed is True
    assert res.travel_time_s <= res.baseline_travel_time_s
    assert res.final_state is not None


def test_route_recalculates_around_blocked_road(graph, healthy):
    from app.models import Action
    from app.tools.traffic import shortest_route

    baseline = shortest_route(graph, healthy, "DEPOT", "H1")
    blocked = apply_action(healthy, graph, Action(
        tool="traffic.close_edge", entity_ids=["E_J4_J6_U1"],
        params={"edge_id": "E_J4_J6_U1"},
    ))
    recalculated = shortest_route(graph, blocked, "DEPOT", "H1")
    assert baseline["reachable"] and recalculated["reachable"]
    assert "E_J4_J6_U1" not in recalculated["edges"]
    assert recalculated["travel_s"] > baseline["travel_s"]
