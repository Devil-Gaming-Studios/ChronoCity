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
