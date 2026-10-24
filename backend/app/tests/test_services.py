from app.city.build_city import build_demo_city
from app.models import Action, InfrastructureAsset
from app.sim.state import apply_action, initial_state
from app.api.commands import CommandRequest, parse_command


def test_power_overload_identifies_failed_station():
    graph = build_demo_city()
    state = apply_action(
        initial_state(graph),
        graph,
        Action(tool="power.set_load", entity_ids=["S2"], params={"substation_id": "S2", "load_mw": 45}),
    )
    assert state.failed_assets["S2"] == "overload"
    assert state.powered["F3"] is False
    assert state.signals_ok["SIG_J5"] is False


def test_water_pipe_break_is_preserved_in_state():
    graph = build_demo_city()
    graph.infrastructure.append(InfrastructureAsset(id="PIPE-1", kind="pipeline", name="North Main"))
    state = apply_action(
        initial_state(graph),
        graph,
        Action(tool="water.break_pipe", entity_ids=["PIPE-1"], params={"asset_id": "PIPE-1"}),
    )
    assert state.water_failures["PIPE-1"] == "pipe break"
    assert state.water_pressure_kpa["PIPE-1"] == 0.0


def test_command_parser_supports_rain_and_selected_disable():
    parsed, sim = parse_command(CommandRequest(text="rain 120 mm"))
    assert parsed["intent"] == "rain"
    assert sim is not None and sim.hazards[0].type == "rain"

    parsed, sim = parse_command(CommandRequest(text="disable selected feature", selected_entity_id="E_J4_J6_U1", selected_entity_type="edge"))
    assert parsed["intent"] == "close_edge"
    assert sim is not None and sim.hazards[0].edge_id == "E_J4_J6_U1"


def test_demo_hospital_has_department_capacity():
    hospital = build_demo_city().hospitals[0]
    assert hospital.departments
    assert sum(item.available_beds for item in hospital.departments) > 0


def test_heavy_traffic_command_targets_selected_road(graph, healthy):
    parsed, sim = parse_command(
        CommandRequest(
            text="heavy traffic on the selected road",
            selected_entity_id="E_J4_J6_U1",
            selected_entity_type="edge",
        )
    )
    assert parsed["intent"] == "heavy_traffic"
    assert sim is not None and sim.hazards[0].type == "heavy_traffic"

    from app.api.simulations import _hazard_actions
    actions = _hazard_actions(sim.hazards[0], graph)
    updated = apply_action(healthy, graph, actions[0])
    assert updated.edge_factor["E_J4_J6_U1"] == 2.0
    assert updated.edge_travel_s["E_J4_J6_U1"] > healthy.edge_travel_s["E_J4_J6_U1"]


def test_multiple_node_disruptions_close_incident_roads(graph, healthy):
    from app.models import Action

    updated = apply_action(healthy, graph, Action(
        tool="traffic.disable_node",
        entity_ids=["J4", "J5"],
        params={"node_ids": ["J4", "J5"]},
    ))
    assert updated.closed_edges["E_J4_J5"] is True
    assert updated.closed_edges["E_J4_J6_U1"] is True
    assert updated.closed_edges["E_J5_J7"] is True
    assert updated.signals_ok["SIG_J4"] is False
    assert updated.signals_ok["SIG_J5"] is False


def test_power_generation_can_create_and_restore_outage(graph, healthy):
    low = apply_action(healthy, graph, Action(
        tool="power.set_generation", entity_ids=["S2"],
        params={"substation_id": "S2", "generation_mw": 10},
    ))
    assert low.power_generation_mw["S2"] == 10
    assert low.failed_assets["S2"] == "generation shortfall"
    assert low.signals_ok["SIG_J5"] is False

    restored = apply_action(low, graph, Action(
        tool="power.set_generation", entity_ids=["S2"],
        params={"substation_id": "S2", "generation_mw": 35},
    ))
    assert restored.power_generation_mw["S2"] == 35
    assert restored.signals_ok["SIG_J5"] is True


def test_command_parser_supports_multiple_roads_and_generation():
    parsed, sim = parse_command(CommandRequest(text="close roads E_J4_J6_U1, E_J5_J7"))
    assert parsed["edge_ids"] == ["E_J4_J6_U1", "E_J5_J7"]
    assert sim is not None and sim.hazards[0].edge_ids == ["E_J4_J6_U1", "E_J5_J7"]

    parsed, sim = parse_command(CommandRequest(text="set station S2 generation to 18 MW"))
    assert parsed["intent"] == "power_generation"
    assert sim is not None and sim.hazards[0].generation_mw == 18
