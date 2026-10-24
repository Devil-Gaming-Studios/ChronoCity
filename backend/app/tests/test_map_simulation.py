"""HTTP regressions for cumulative preview, rerouting and power coverage."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Action, Edge
from app.sim.state import apply_action, reachable_travel_time
from app.tools.traffic import shortest_route


@pytest.fixture
def client(monkeypatch):
    from app.ingest.bus import MemoryBus
    monkeypatch.setattr("app.main.get_bus", MemoryBus)
    with TestClient(create_app()) as session:
        yield session


def preview(client, hazards, base=None):
    response = client.post("/api/simulations/run", json={"hazards": hazards, "base_state": base})
    assert response.status_code == 200, response.text
    return response.json()["after_state"]


def route(client, state):
    response = client.post("/api/routes/vehicles", json={
        "vehicle_type": "ambulance", "origin": "DEPOT", "hospital_id": "H1", "state": state,
    })
    assert response.status_code == 200, response.text
    return response.json()["route"]


def test_cumulative_previews_reroute_without_mutating_live(client):
    live = client.get("/api/timeline").json()["present"]
    original = route(client, live)
    first = preview(client, [{"type": "close_edge", "edge_id": "E_J4_J6_U1"}], live)
    second = preview(client, [{"type": "flood", "edge_ids": ["E_J5_J7", "E_J7_H1"], "depth_cm": 80}], first)
    assert second["closed_edges"]["E_J4_J6_U1"]
    assert second["flooded_edges"]["E_J5_J7"] == 80
    detour = route(client, second)
    assert detour["reachable"]
    assert detour["edges"] != original["edges"]
    assert not set(detour["edges"]) & {"E_J4_J6_U1", "E_J5_J7", "E_J7_H1"}
    assert client.get("/api/timeline").json()["present"] == live


def test_unreachable_route_is_valid_json_and_has_no_path(client):
    state = preview(client, [{"type": "close_edge", "edge_ids": ["E_J8_H1", "E_J7_H1"]}])
    result = route(client, state)
    assert result == {"src": "DEPOT", "dst": "H1", "reachable": False, "travel_s": None, "edges": [], "nodes": []}


def test_route_recomputes_untrusted_cached_weights(client):
    state = preview(client, [{"type": "close_edge", "edge_id": "E_J4_J6_U1"}])
    state["edge_travel_s"]["E_J4_J6_U1"] = 0
    assert "E_J4_J6_U1" not in route(client, state)["edges"]


def test_multiple_nodes_block_all_incident_roads(client):
    state = preview(client, [{"type": "flood_node", "node_ids": ["J4", "J5"], "depth_cm": 50}])
    assert {"E_J1_J4", "E_J4_J5", "E_J4_J6_U1", "E_J5_J7", "E_J5_J8"} <= set(state["flooded_edges"])
    assert route(client, state)["reachable"]


def test_command_extends_caller_branch(client):
    first = preview(client, [{"type": "close_edge", "edge_id": "E_J4_J6_U1"}])
    response = client.post("/api/commands/run", json={"text": "disable nodes J5, J8", "base_state": first})
    assert response.status_code == 200
    assert response.json()["after_state"]["closed_edges"]["E_J4_J6_U1"]
    assert response.json()["after_state"]["closed_edges"]["E_J5_J8"]


def test_preview_power_reads_branch_and_reports_mapped_outage(client):
    low = preview(client, [{"type": "power_generation", "substation_id": "S2", "generation_mw": 10}])
    response = client.post("/api/infrastructure/diagnostics/preview", json={"state": low})
    assert response.status_code == 200
    info = response.json()
    station = next(item for item in info["stations"] if item["substation_id"] == "S2")
    assert station["generation_mw"] == 10
    assert station["output_mw"] == 0
    assert set(info["affected_nodes"]) == {"J5", "J6", "J7", "J8", "N7"}
    assert set(info["affected_zones"]) == {"Z2", "Z3"}
    assert client.get("/api/infrastructure/diagnostics").json()["affected_nodes"] == []
    recovered = preview(client, [{"type": "power_generation", "substation_id": "S2", "generation_mw": 35}], low)
    info = client.post("/api/infrastructure/diagnostics/preview", json={"state": recovered}).json()
    assert info["affected_nodes"] == []


def test_load_shortfall_and_explicit_trip_are_not_cleared_by_editing_supply(client):
    low = preview(client, [{"type": "power_overload", "substation_id": "S2", "load_mw": 35}])
    assert low["failed_assets"]["S2"] == "generation shortfall"
    tripped = preview(client, [{"type": "power_outage", "substation_id": "S2"}], low)
    edited = preview(client, [{"type": "power_generation", "substation_id": "S2", "generation_mw": 40}], tripped)
    assert edited["failed_assets"]["S2"] == "substation trip"
    assert edited["powered"]["F3"] is False
    restored = preview(client, [{"type": "power_restore", "substation_id": "S2"}], edited)
    assert restored["powered"]["F3"] is True


@pytest.mark.parametrize("hazard", [
    {"type": "flood", "edge_ids": ["NOT_A_ROAD"]},
    {"type": "disable_node", "node_ids": ["NOT_A_NODE"]},
    {"type": "power_generation", "substation_id": "S2", "generation_mw": -1},
    {"type": "power_generation", "substation_id": "S2", "generation_mw": 41},
])
def test_invalid_hazards_are_rejected(client, hazard):
    assert client.post("/api/simulations/run", json={"hazards": [hazard]}).status_code == 422


def test_feeders_never_become_ambulance_shortcuts(graph, healthy):
    graph = graph.model_copy(deep=True)
    graph.edges.append(Edge(id="UTILITY", src="DEPOT", dst="H1", kind="feeder", length_m=1))
    healthy.edge_travel_s["UTILITY"] = 0.01
    assert "UTILITY" not in shortest_route(graph, healthy, "DEPOT", "H1")["edges"]
    assert reachable_travel_time(healthy, graph, "DEPOT", "H1") > 1


def test_node_failure_is_not_misreported_as_regional_power_failure(client):
    state = preview(client, [{"type": "disable_node", "node_ids": ["J5"]}])
    assert not state["signals_ok"]["SIG_J5"]
    info = client.post("/api/infrastructure/diagnostics/preview", json={"state": state}).json()
    assert info["affected_nodes"] == []
