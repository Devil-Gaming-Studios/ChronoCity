"""Persistence and operator control regressions through the public HTTP flow."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.audit import AuditStore
from app.main import create_app
from app.models import Action, JointPlan, PlanStatus
from app.sim.state import apply_action


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.ingest.bus import MemoryBus
    monkeypatch.setattr("app.main.get_bus", MemoryBus)
    with TestClient(create_app(str(tmp_path / "history.sqlite3"))) as session:
        yield session


def events(client, **params):
    response = client.get("/api/audit/events", params={"limit": 200, **params})
    assert response.status_code == 200
    return response.json()


def manual_plan(client):
    response = client.post("/api/plans/manual", json={"actions": [{
        "tool": "traffic.retime_signals", "entity_ids": ["SIG_J1"],
        "params": {"signal_ids": ["SIG_J1"], "cycle_s": 45}, "impact": "LOW",
    }]})
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["status"] == "PENDING_APPROVAL"
    return plan["id"]


def test_city_previews_complaints_routes_and_invalid_requests_are_recorded(client):
    live = client.get("/api/timeline").json()["present"]
    simulation = client.post("/api/simulations/run", json={"hazards": [
        {"type": "close_edge", "edge_id": "E_J4_J6_U1"},
        {"type": "power_generation", "substation_id": "S2", "generation_mw": 10},
    ]}).json()
    pipeline = client.post("/api/community/pipeline-preview", json={"asset_id": "PIPE_Z1", "pressure_kpa": 10}).json()
    client.post("/api/community/complaints", json={"zone": "Z1", "category": "pipe_leak", "count": 50,
        "text": "<script>Never execute this complaint text</script>", "state": pipeline["after_state"]})
    client.post("/api/routes/vehicles", json={"vehicle_type": "ambulance", "hospital_id": "H1", "state": simulation["after_state"]})
    assert client.post("/api/community/pipeline-preview", json={"asset_id": "PIPE_Z1", "pressure_kpa": -1}).status_code == 422
    items = events(client)["items"]
    assert {"simulation_complete", "pipeline_preview", "complaint_inflow", "route_recalculated", "request_completed"} <= {e["kind"] for e in items}
    preview = next(e for e in items if e["kind"] == "simulation_complete")
    assert preview["scope"] == "preview"
    assert preview["payload"]["after_state"]["closed_edges"]["E_J4_J6_U1"]
    complaint = next(e for e in items if e["kind"] == "complaint_inflow")
    assert complaint["payload"]["batch"]["text_trust"] == "untrusted_display_only"
    assert client.get("/api/timeline").json()["present"] == live
    assert client.get("/api/audit/pending").json()["items"] == []


def test_history_survives_restart_and_old_plans_are_read_only(tmp_path):
    path = str(tmp_path / "durable.sqlite3")
    with TestClient(create_app(path)) as first:
        plan_id = manual_plan(first)
        first.post("/api/commands/run", json={"text": "close roads E_J4_J6_U1"})
        count = events(first)["total"]
        runtime = events(first)["runtime_id"]
    with TestClient(create_app(path)) as second:
        assert events(second)["total"] > count
        assert events(second)["runtime_id"] != runtime
        saved = second.get("/api/audit/plans").json()["items"]
        assert saved[0]["plan"]["id"] == plan_id
        assert saved[0]["actionable"] is False
        assert second.get("/api/audit/pending").json()["items"] == []
        assert second.post("/api/plans/approve", json={"plan_id": plan_id}).json()["ok"] is False
        assert events(second, kind="command_received")["total"] == 1


def test_operator_approval_note_execution_and_duplicate_safety(client):
    plan_id = manual_plan(client)
    before = client.get("/api/timeline").json()["present"]
    assert client.post("/api/plans/execute", json={"plan_id": plan_id}).json()["error"] == "approval_required"
    approved = client.post("/api/plans/approve", json={"plan_id": plan_id, "note": "Checked affected service points"}).json()
    assert approved["ok"]
    assert client.get("/api/timeline").json()["present"] == before
    assert client.post("/api/plans/execute", json={"plan_id": plan_id}).json()["ok"]
    assert client.get("/api/timeline").json()["present"]["signal_timing_s"]["SIG_J1"] == 45
    assert client.post("/api/plans/execute", json={"plan_id": plan_id}).json()["ok"] is False
    decisions = events(client, kind="operator_decision", plan_id=plan_id)["items"]
    assert decisions[0]["payload"]["note"] == "Checked affected service points"
    assert client.get("/api/audit/plans").json()["items"][0]["plan"]["status"] == "EXECUTED"
    assert client.get("/api/audit/pending").json()["items"] == []


@pytest.mark.parametrize("withdraw", [False, True])
def test_reject_or_withdraw_low_impact_plan_cannot_execute(client, withdraw):
    plan_id = manual_plan(client)
    if withdraw:
        assert client.post("/api/plans/approve", json={"plan_id": plan_id}).json()["ok"]
    assert client.post("/api/plans/approve", json={"plan_id": plan_id, "approved": False, "note": "Do not proceed"}).json()["ok"]
    assert client.post("/api/plans/execute", json={"plan_id": plan_id}).json()["ok"] is False


def test_stale_plan_and_reset_invalidate_prior_approvals(client):
    plan_id = manual_plan(client)
    assert client.post("/api/plans/approve", json={"plan_id": plan_id}).json()["ok"]
    client.post("/api/simulations/tick", json={"ticks": 1})
    assert client.get("/api/audit/pending").json()["items"][0]["stale"]
    assert client.post("/api/plans/execute", json={"plan_id": plan_id}).json()["error"] == "stale_plan_generate_again"
    client.post("/api/scenarios/reset")
    assert client.get("/api/audit/pending").json()["items"] == []
    assert client.get("/api/audit/plans").json()["items"][0]["plan"]["status"] == "FAILED"


def test_edits_are_reverified_versioned_and_preserved(client):
    plan_id = manual_plan(client)
    action_id = client.get("/api/plans/current").json()["actions"][0]["id"]
    result = client.post("/api/plans/edit", json={"plan_id": plan_id, "remove_action_ids": [action_id]}).json()
    assert result["ok"]
    saved = client.get("/api/audit/plans").json()["items"][0]["plan"]
    assert saved["version"] == 2 and saved["actions"] == []
    snapshots = events(client, kind="plan_snapshot", plan_id=plan_id)["items"]
    assert {e["payload"]["plan"]["version"] for e in snapshots} == {1, 2}


def test_water_isolation_requires_verified_live_evidence_and_operator_approval(client):
    assert client.post("/api/plans/generate").status_code == 409
    orch = client.app.state.orchestrator
    orch.state = apply_action(orch.state, orch.graph, Action(tool="water.break_pipe", params={"asset_id": "PIPE_Z1"}))
    result = client.post("/api/plans/generate")
    assert result.status_code == 200, result.text
    plan = result.json()["plan"]
    assert any(a["tool"] == "water.isolate_pipeline" and a["impact"] == "HIGH" for a in plan["actions"])
    assert not orch.state.water_isolated
    assert client.post("/api/plans/execute", json={"plan_id": plan["id"]}).json()["ok"] is False
    assert client.post("/api/plans/approve", json={"plan_id": plan["id"]}).json()["ok"]
    assert client.post("/api/plans/execute", json={"plan_id": plan["id"]}).json()["ok"]
    assert orch.state.water_isolated["PIPE_Z1"]
    assert orch.state.water_failures["PIPE_Z1"] == "pipe break"
    assert events(client, kind="agent_action")["total"] > 0


def test_pagination_has_no_loss_and_filters_are_parameterized(tmp_path):
    store = AuditStore(str(tmp_path / "page.sqlite3"))
    for index in range(220):
        store.record("test_event", {"index": index}, scope="preview")
    first = store.page(limit=200)
    second = store.page(limit=200, before=first["next_before"])
    assert len(first["items"]) == 200 and len(second["items"]) == 20
    assert not {e["id"] for e in first["items"]} & {e["id"] for e in second["items"]}
    assert store.page(kind="'; DROP TABLE audit_events; --")["total"] == 0
    assert store.page(scope="preview")["total"] == 220
    store.close()
