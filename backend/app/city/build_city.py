from __future__ import annotations

import networkx as nx

from ..models import (
    CityGraph,
    Edge,
    Feeder,
    Hospital,
    HospitalDepartment,
    Node,
    Signal,
    Shelter,
    Substation,
    Underpass,
)


def build_demo_city() -> CityGraph:
    """A small hand-built city with a grid of junctions, two substations,
    an underpass that floods, and a hospital.

    Layout (x → east, y → north):

        N6---J2---J3---N7
        |    |    |    |
        J1---J4---J5---J8
        |    |    |    |
        N5---J6---J7---H1(hospital)

    Underpass U1 sits on edge J4-J6 (a low-lying cut-through).
    Substation S1 feeds the north, S2 feeds the south/east.
    """
    nodes: list[Node] = [
        Node(id="J1", kind="junction", x=0, y=2, zone="Z1", name="J1"),
        Node(id="J2", kind="junction", x=2, y=2, zone="Z1", name="J2"),
        Node(id="J3", kind="junction", x=4, y=2, zone="Z1", name="J3"),
        Node(id="J4", kind="junction", x=2, y=1, zone="Z1", name="J4"),
        Node(id="J5", kind="junction", x=4, y=1, zone="Z2", name="J5"),
        Node(id="J6", kind="junction", x=2, y=0, zone="Z2", name="J6"),
        Node(id="J7", kind="junction", x=4, y=0, zone="Z2", name="J7"),
        Node(id="J8", kind="junction", x=6, y=1, zone="Z2", name="J8"),
        Node(id="N5", kind="junction", x=0, y=0, zone="Z2", name="N5"),
        Node(id="N6", kind="junction", x=0, y=3, zone="Z1", name="N6"),
        Node(id="N7", kind="junction", x=6, y=3, zone="Z3", name="N7"),
        Node(id="H1", kind="hospital", x=6, y=0, zone="Z3", name="City General"),
        Node(id="S1", kind="substation", x=1, y=3, zone="Z1", name="Substation S1"),
        Node(id="S2", kind="substation", x=5, y=-1, zone="Z2", name="Substation S2"),
        Node(id="DEPOT", kind="depot", x=-1, y=1, zone="Z0", name="Ambulance Depot"),
        Node(id="SH1", kind="shelter", x=0, y=-1, zone="Z2", name="Riverside Shelter"),
    ]

    def road(eid: str, src: str, dst: str, length: float, kind: str = "road") -> Edge:
        return Edge(id=eid, src=src, dst=dst, length_m=length, kind=kind)  # type: ignore[arg-type]

    edges: list[Edge] = [
        road("E_N6_J2", "N6", "J2", 200),
        road("E_J2_J3", "J2", "J3", 200),
        road("E_J3_N7", "J3", "N7", 200),
        road("E_N6_J1", "N6", "J1", 300),
        road("E_J1_J4", "J1", "J4", 200),
        road("E_J4_J5", "J4", "J5", 200),
        road("E_J5_J8", "J5", "J8", 200),
        road("E_N7_J8", "N7", "J8", 300),
        road("E_J1_N5", "J1", "N5", 200),
        # the flood-prone underpass cut-through
        road("E_J4_J6_U1", "J4", "J6", 120, kind="underpass"),
        road("E_J6_J7", "J6", "J7", 200),
        road("E_J7_H1", "J7", "H1", 200),
        road("E_J5_J7", "J5", "J7", 200),
        road("E_N5_J6", "N5", "J6", 200),
        road("E_J8_H1", "J8", "H1", 200),
        road("E_DEPOT_J1", "DEPOT", "J1", 150),
        road("E_SH1_N5", "SH1", "N5", 180),
        # utility connectors keep the infrastructure graph connected without
        # changing the road topology used for ordinary route planning.
        road("E_S1_N6", "S1", "N6", 100, kind="feeder"),
        road("E_S2_J7", "S2", "J7", 100, kind="feeder"),
    ]

    substations = [
        Substation(id="S1", node_id="S1", feeders=["F1", "F2"], capacity_mw=40),
        Substation(id="S2", node_id="S2", feeders=["F3", "F4"], capacity_mw=40),
    ]

    feeders = [
        Feeder(id="F1", substation_id="S1", serves=["SIG_J1", "SIG_J2", "SIG_J3", "SIG_J4"]),
        Feeder(id="F2", substation_id="S1", serves=["SIG_N5", "SIG_N6"]),
        Feeder(id="F3", substation_id="S2", serves=["SIG_J5", "SIG_J6", "SIG_J7"]),
        Feeder(id="F4", substation_id="S2", serves=["SIG_J8", "SIG_N7"]),
    ]

    signals = [
        Signal(id="SIG_J1", node_id="J1", feeder_id="F1"),
        Signal(id="SIG_J2", node_id="J2", feeder_id="F1"),
        Signal(id="SIG_J3", node_id="J3", feeder_id="F1"),
        Signal(id="SIG_J4", node_id="J4", feeder_id="F1"),
        Signal(id="SIG_N5", node_id="N5", feeder_id="F2"),
        Signal(id="SIG_N6", node_id="N6", feeder_id="F2"),
        Signal(id="SIG_J5", node_id="J5", feeder_id="F3"),
        Signal(id="SIG_J6", node_id="J6", feeder_id="F3"),
        Signal(id="SIG_J7", node_id="J7", feeder_id="F3"),
        Signal(id="SIG_J8", node_id="J8", feeder_id="F4"),
        Signal(id="SIG_N7", node_id="N7", feeder_id="F4"),
    ]

    hospitals = [
        Hospital(
            id="H1",
            node_id="H1",
            name="City General",
            departments=[
                HospitalDepartment(id="H1-ED", name="Emergency", total_beds=24, available_beds=12),
                HospitalDepartment(id="H1-ICU", name="ICU", total_beds=10, available_beds=4),
                HospitalDepartment(id="H1-SURG", name="Surgery", total_beds=16, available_beds=8),
            ],
        )
    ]
    underpasses = [Underpass(id="U1", edge_id="E_J4_J6_U1", name="River Road Underpass")]
    shelters = [Shelter(id="SH1", node_id="SH1", name="Riverside Shelter", capacity=250, available=250)]

    return CityGraph(
        nodes=nodes,
        edges=edges,
        substations=substations,
        feeders=feeders,
        signals=signals,
        hospitals=hospitals,
        shelters=shelters,
        underpasses=underpasses,
        source="demo",
        source_ref="built-in",
        name="ChronoTwin Demo City",
    )


def to_networkx(graph: CityGraph) -> nx.MultiDiGraph:
    """Build an undirected-weighted NetworkX view for routing (both directions)."""
    g = nx.MultiDiGraph()
    for n in graph.nodes:
        g.add_node(n.id, **n.model_dump())
    for e in graph.edges:
        # travel time from free-flow speed
        speed_mps = max(e.free_flow_kph, 1.0) / 3.6
        t = e.length_m / speed_mps
        g.add_edge(e.src, e.dst, id=e.id, weight=t, length_m=e.length_m, kind=e.kind)
        g.add_edge(e.dst, e.src, id=e.id + "_rev", weight=t, length_m=e.length_m, kind=e.kind)
    return g


def edge_index(graph: CityGraph) -> dict[str, Edge]:
    return {e.id: e for e in graph.edges}


__all__ = ["build_demo_city", "to_networkx", "edge_index"]
