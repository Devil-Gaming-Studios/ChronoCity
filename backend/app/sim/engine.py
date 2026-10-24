from __future__ import annotations

from typing import Any

from ..models import CityGraph, CitySnapshot, JointPlan, SimulationResult
from .state import advance_tick, apply_action, initial_state, reachable_travel_time


def _metrics(state: CitySnapshot, graph: CityGraph, ambulance_edge: str | None) -> dict[str, float]:
    dark = sum(1 for sig in graph.signals if not state.signals_ok.get(sig.id, True))
    tt = 0.0
    if ambulance_edge:
        edge = next((e for e in graph.edges if e.id == ambulance_edge), None)
        if edge:
            hosp = graph.hospitals[0].node_id if graph.hospitals else "H1"
            tt = reachable_travel_time(state, graph, edge.src, hosp)
    return {"dark_signals": float(dark), "ambulance_travel_s": tt}


def simulate(
    graph: CityGraph,
    plan: JointPlan,
    baseline: CitySnapshot | None = None,
    start_state: CitySnapshot | None = None,
) -> SimulationResult:
    """Deterministically replay a joint plan's actions against the twin.

    The comparison baseline is the state the plan starts from (usually the
    failed state), so gains are always "before plan vs after plan".

    Fails if:
      * the hospital becomes unreachable,
      * ambulance travel time gets worse than the start state,
      * any signal is still dark after the plan (cascade not contained).
    """
    base = start_state if start_state is not None else (baseline or initial_state(graph))
    state = base.model_copy(deep=True)

    # which ambulance edge are we timing?
    amb_edge = None
    for a in plan.actions:
        if a.tool == "emergency.dispatch":
            amb_edge = a.params.get("from_edge") or (a.entity_ids[0] if a.entity_ids else None)

    base_metrics = _metrics(base, graph, amb_edge)
    trace: list[dict[str, Any]] = []
    for action in plan.actions:
        state = apply_action(state, graph, action)
        trace.append({"tool": action.tool, "params": action.params, "metrics": _metrics(state, graph, amb_edge)})

    m = _metrics(state, graph, amb_edge)
    base_tt = base_metrics["ambulance_travel_s"]
    new_tt = m["ambulance_travel_s"]
    base_dark = int(base_metrics["dark_signals"])
    new_dark = int(m["dark_signals"])

    notes: list[str] = []
    passed = True

    hosp_node = graph.hospitals[0].node_id if graph.hospitals else "H1"
    if new_tt == float("inf"):
        passed = False
        notes.append(f"Hospital {hosp_node} unreachable after plan.")

    if new_tt > base_tt and base_tt != float("inf"):
        passed = False
        notes.append(f"Ambulance travel time worsened ({base_tt:.0f}s -> {new_tt:.0f}s).")

    if new_dark > 0:
        passed = False
        notes.append(f"{new_dark} signal(s) still dark after plan (cascade not contained).")

    # score: improvement in ambulance travel time + reduction in dark signals
    tt_gain = 0.0 if base_tt in (0.0, float("inf")) else (base_tt - new_tt) / base_tt
    dark_gain = (base_dark - new_dark) / max(base_dark, 1.0)
    score = round(0.7 * tt_gain + 0.3 * dark_gain, 4)

    contained = _containment_hops(graph, state)
    jammed = sum(1 for edge in graph.edges if edge.kind == "road" and state.edge_travel_s.get(edge.id, 0.0) > (edge.length_m / (max(edge.free_flow_kph, 1.0) / 3.6)) * 1.4)
    if contained > 2:
        notes.append(f"Cascade reached {contained} hops (>2).")

    return SimulationResult(
        plan_id=plan.id,
        passed=passed,
        score=score,
        travel_time_s=new_tt if new_tt != float("inf") else -1.0,
        baseline_travel_time_s=base_tt if base_tt != float("inf") else -1.0,
        dark_junctions=new_dark,
        contained_hops=contained,
        jammed_arterials=jammed,
        blocked_edges=sorted(set(state.flooded_edges) | {eid for eid, closed in state.closed_edges.items() if closed}),
        notes=notes,
        trace=trace,
        final_state=state.model_dump(),
    )


def _containment_hops(graph: CityGraph, state: CitySnapshot) -> int:
    from ..city.cascade import trace_cascade

    dark_nodes = {s.node_id for s in graph.signals if not state.signals_ok.get(s.id, True)}
    roots: list[str] = list(state.flooded_edges.keys()) + list(state.closed_edges.keys())
    if not roots:
        roots = sorted(dark_nodes)
    if not roots:
        return 0
    result = trace_cascade(graph, roots, blocked_edges=set(state.flooded_edges), dark_nodes=dark_nodes)
    return int(result.get("contained_hops", 0))


def run_ticks(graph: CityGraph, state: CitySnapshot, ticks: int, seconds_per_tick: float = 1.0) -> CitySnapshot:
    """Fork and advance a snapshot for a discrete-event simulation window."""
    out = state.model_copy(deep=True)
    for _ in range(max(0, ticks)):
        out = advance_tick(out, graph, seconds_per_tick)
    return out


__all__ = ["simulate", "run_ticks", "initial_state", "apply_action", "reachable_travel_time"]
