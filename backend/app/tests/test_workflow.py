from __future__ import annotations

import pytest

from app.agents.orchestrator import Orchestrator
from app.agents.workflow import Workflow
from app.city.build_city import build_demo_city
from app.models import ValidatedSignal


def _combined_signals():
    from app.api.scenarios import _signals_for

    return _signals_for("combined", build_demo_city())


async def test_combined_pipeline_end_to_end():
    """detect -> plan (parallel) -> negotiate -> critic rejects -> revise -> passes."""
    graph = build_demo_city()
    orch = Orchestrator(graph)
    wf = Workflow(orch, graph)

    # open the twin in the failed combined state (as scenarios._run does)
    from app.sim.scenarios import combined_incidents, combined_state

    orch.state = combined_state(graph)
    wf.detect(_combined_signals())
    for inc in combined_incidents(graph):
        orch.add_incident(inc)
    assert orch.open_incidents(), "detection must produce incidents"

    plan = await wf.plan()

    # critic must have rejected v1 and the revision must have passed
    assert plan.version >= 2, "critic should force at least one revision"
    assert plan.status.value in ("VERIFIED", "PENDING_APPROVAL")
    assert plan.metrics.get("dark_junctions", 1) == 0
    assert plan.needs_revision is False
    # conflict seeded + resolved
    assert plan.resolution
    # LLM calls scale with incidents, not readings: far fewer calls than readings
    wf._readings_seen = len(_combined_signals())  # as scenarios._run records
    m = wf.metrics()
    assert m["readings_processed"] >= 8
    assert m["llm_calls"] <= m["readings_processed"]


async def test_high_impact_requires_approval():
    graph = build_demo_city()
    orch = Orchestrator(graph)
    wf = Workflow(orch, graph)
    from app.sim.scenarios import combined_incidents, combined_state

    orch.state = combined_state(graph)
    wf.detect(_combined_signals())
    for inc in combined_incidents(graph):
        orch.add_incident(inc)
    plan = await wf.plan()
    assert plan.status.value == "PENDING_APPROVAL"

    # executing without approval must be refused
    out = wf.execute(plan.id)
    assert out["ok"] is False and out["error"] == "approval_required"

    # approve then execute
    appr = wf.approve(plan.id, approver="operator", note="verified by critic")
    assert appr["ok"] and appr["approved"]
    out2 = wf.execute(plan.id)
    assert out2["ok"] and out2["executed"] >= 1

    # every execution is in the action log
    executed = [e for e in orch.action_log if e.phase == "execute"]
    assert len(executed) == out2["executed"]
    # incidents addressed by the plan are resolved
    assert not [i for i in orch.incidents if i.id in plan.incident_ids and not i.resolved]


async def test_rejecting_approval_blocks_execution():
    graph = build_demo_city()
    orch = Orchestrator(graph)
    wf = Workflow(orch, graph)
    from app.sim.scenarios import combined_state

    orch.state = combined_state(graph)
    wf.detect(_combined_signals())
    plan = await wf.plan()
    out = wf.approve(plan.id, approved=False, note="too risky")
    assert out["ok"] and out["approved"] is False
    out2 = wf.execute(plan.id)
    assert out2["ok"] is False


def test_low_trust_never_creates_incident():
    """Fake/poisoned report: trust below the gate produces NO incident."""
    from app.ingest.aggregator import Aggregator
    from app.ingest.anomaly import AnomalyDetector

    graph = build_demo_city()
    det = AnomalyDetector(graph, trust_threshold=0.5)
    agg = Aggregator(window_seconds=0.0)
    agg.add(ValidatedSignal(source="report", zone="Z1", kind="water_level_cm",
                            value=500.0, trust=0.2))  # fake flood, low trust
    summaries = agg.flush()
    assert summaries
    assert det.detect(summaries) == []


async def test_aggregator_reduces_data():
    """Many readings collapse to one summary per (zone, kind)."""
    from app.ingest.aggregator import Aggregator

    agg = Aggregator(window_seconds=0.0)
    for i in range(50):
        agg.add(ValidatedSignal(source="sensor", zone="Z1", kind="water_level_cm",
                                value=float(10 + i), trust=0.9))
    agg.add(ValidatedSignal(source="sensor", zone="Z2", kind="power_draw_kw",
                            value=40000.0, trust=0.9))
    out = agg.flush()
    assert len(out) == 2  # 51 readings -> 2 summaries
