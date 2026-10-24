from __future__ import annotations

from typing import Any

from ..models import (
    Action,
    CityGraph,
    CitySnapshot,
    Incident,
    IncidentSeverity,
    SensorReading,
)
from .state import apply_action, initial_state


def flood_readings(graph: CityGraph, t: float = 0.0) -> list[SensorReading]:
    """Rising water on the underpass U1 edge."""
    return [
        SensorReading(sensor_id="WL_U1", zone="Z1", kind="water_level_cm", value=12.0, ts=t, trust=0.95),
        SensorReading(sensor_id="WL_U1", zone="Z1", kind="water_level_cm", value=35.0, ts=t + 2, trust=0.95),
        SensorReading(sensor_id="WL_U1", zone="Z1", kind="water_level_cm", value=78.0, ts=t + 4, trust=0.95),
        SensorReading(sensor_id="WL_U1", zone="Z1", kind="water_level_cm", value=140.0, ts=t + 6, trust=0.95),
    ]


def trip_readings(graph: CityGraph, t: float = 0.0) -> list[SensorReading]:
    """S2 power draw spikes then collapses as the substation trips."""
    return [
        SensorReading(sensor_id="PWR_S2", zone="Z2", kind="power_draw_kw", value=38000, ts=t, trust=0.98),
        SensorReading(sensor_id="PWR_S2", zone="Z2", kind="power_draw_kw", value=41000, ts=t + 1, trust=0.98),
        SensorReading(sensor_id="PWR_S2", zone="Z2", kind="power_draw_kw", value=1200, ts=t + 2, trust=0.98),
        SensorReading(sensor_id="SIG_J5", zone="Z2", kind="signal_ok", value=0.0, ts=t + 3, trust=0.9),
        SensorReading(sensor_id="SIG_J6", zone="Z2", kind="signal_ok", value=0.0, ts=t + 3, trust=0.9),
        SensorReading(sensor_id="SIG_J7", zone="Z2", kind="signal_ok", value=0.0, ts=t + 3, trust=0.9),
    ]


def flood_incident(graph: CityGraph) -> Incident:
    up = graph.underpasses[0]
    return Incident(
        kind="flood",
        severity=IncidentSeverity.CRITICAL,
        zone="Z1",
        entity_ids=[up.edge_id, up.id],
        title="Underpass U1 flooding",
        detail=f"Water level critical on {up.name}; edge {up.edge_id} impassable.",
        priority=1,
        trust=0.95,
        dedupe_key="flood:U1",
    )


def trip_incident(graph: CityGraph) -> Incident:
    sub = next(s for s in graph.substations if s.id == "S2")
    dark = [sig.id for sig in graph.signals if sig.feeder_id in sub.feeders]
    return Incident(
        kind="substation_trip",
        severity=IncidentSeverity.CRITICAL,
        zone="Z2",
        entity_ids=[sub.id, *dark],
        title="Substation S2 trip",
        detail=f"S2 tripped; feeders {sub.feeders} down; signals dark: {', '.join(dark)}.",
        priority=1,
        trust=0.98,
        dedupe_key="trip:S2",
    )


def gridlock_incident(graph: CityGraph) -> Incident:
    return Incident(
        kind="gridlock",
        severity=IncidentSeverity.WARNING,
        zone="Z2",
        entity_ids=["E_J4_J6_U1", "J5", "J7"],
        title="Detour gridlock",
        detail="Traffic diverted from flooded U1 is stacking on J5-J7 corridor.",
        priority=3,
        trust=0.7,
        dedupe_key="gridlock:detour",
    )


def ambulance_delayed_incident(graph: CityGraph) -> Incident:
    return Incident(
        kind="ambulance_delayed",
        severity=IncidentSeverity.CRITICAL,
        zone="Z2",
        entity_ids=["A1", "H1"],
        title="Ambulance A1 delayed to H1",
        detail="Fastest route to City General cut by flood + dark signals.",
        priority=1,
        trust=0.9,
        dedupe_key="amb:A1",
    )


def flood_state(graph: CityGraph) -> CitySnapshot:
    """State with the underpass flooded."""
    s = initial_state(graph)
    return apply_action(
        s, graph,
        Action(
            tool="traffic.flood_edge",
            entity_ids=["E_J4_J6_U1"],
            params={"edge_id": "E_J4_J6_U1", "depth_cm": 140},
            impact="HIGH",
            rationale="scenario",
            owner="scenario",
        ),
    )


def trip_state(graph: CityGraph) -> CitySnapshot:
    """State with S2 tripped."""
    s = initial_state(graph)
    return apply_action(
        s, graph,
        Action(
            tool="power.trip_substation",
            entity_ids=["S2"],
            params={"substation_id": "S2"},
            impact="HIGH",
            rationale="scenario",
            owner="scenario",
        ),
    )


def combined_state(graph: CityGraph) -> CitySnapshot:
    """Both failures: flood + trip. The demo's opening state."""
    s = flood_state(graph)
    return apply_action(
        s, graph,
        Action(
            tool="power.trip_substation",
            entity_ids=["S2"],
            params={"substation_id": "S2"},
            impact="HIGH",
            rationale="scenario",
            owner="scenario",
        ),
    )


def combined_incidents(graph: CityGraph) -> list[Incident]:
    return [
        flood_incident(graph),
        trip_incident(graph),
        gridlock_incident(graph),
        ambulance_delayed_incident(graph),
    ]


__all__ = [
    "flood_readings",
    "trip_readings",
    "flood_incident",
    "trip_incident",
    "gridlock_incident",
    "ambulance_delayed_incident",
    "flood_state",
    "trip_state",
    "combined_state",
    "combined_incidents",
]
