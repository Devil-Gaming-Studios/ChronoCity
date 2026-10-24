from __future__ import annotations

from typing import Any

from ..models import Action, AgentProposal, CityGraph, CitySnapshot, Incident, Impact
from ..tools import emergency as em
from ..tools import power as pw
from ..tools import traffic as tr
from .callbacks import get_callbacks
from .llm import get_llm


class SpecialistBase:
    domain = "generic"
    name = "specialist"

    def __init__(self, graph: CityGraph) -> None:
        self.graph = graph

    async def run(self, state: CitySnapshot, incidents: list[Incident]) -> AgentProposal:
        raise NotImplementedError


class PowerAgent(SpecialistBase):
    domain = "power"
    name = "power_agent"

    async def run(self, state: CitySnapshot, incidents: list[Incident]) -> AgentProposal:
        read_calls: list[str] = []
        actions: list[Action] = []
        incident_ids = [i.id for i in incidents]

        # 1. READ first (design principle: read tools before proposing)
        tripped = [i for i in incidents if i.kind == "substation_trip"]
        dark: list[dict[str, Any]] = []
        for inc in tripped:
            sid = inc.entity_ids[0] if inc.entity_ids else "S2"
            st = pw.substation_status(self.graph, state, sid)
            read_calls.append(f"power.substation_status({sid})")
            dark.extend(pw.dark_signals(self.graph, state, zone=inc.zone))
            read_calls.append(f"power.dark_signals(zone={inc.zone})")

            # 2. PROPOSE a backfeed from a healthy substation
            healthy = [s for s in self.graph.substations if s.id != sid]
            if healthy:
                src = healthy[0]
                dark_ids = [d["signal_id"] for d in dark]
                # the feeder on the healthy substation closest to the dark zone
                target_feeder = src.feeders[0]
                actions.append(
                    pw.propose_reroute_feeder(
                        from_feeder=sid,
                        to_feeder=target_feeder,
                        serves=dark_ids,
                        rationale=f"Backfeed {len(dark_ids)} dark signals from healthy {src.id} via {target_feeder}.",
                    )
                )
                # keep the healthy substation stable by shedding a non-critical feeder
                if len(src.feeders) > 1:
                    actions.append(
                        pw.propose_load_shed(
                            substation_id=src.id,
                            feeders=[src.feeders[-1]],
                            rationale="Shed non-critical load to free capacity for backfeed.",
                        )
                    )

        summary = await get_callbacks().guarded_complete(self.name, f"Power plan for {incident_ids}")
        get_llm()._record(self.name, "propose")
        return get_llm_proposal(self, incident_ids, summary, actions, read_calls)


class TrafficAgent(SpecialistBase):
    domain = "traffic"
    name = "traffic_agent"

    async def run(self, state: CitySnapshot, incidents: list[Incident]) -> AgentProposal:
        read_calls: list[str] = []
        actions: list[Action] = []
        incident_ids = [i.id for i in incidents]

        floods = [i for i in incidents if i.kind in ("flood", "gridlock")]
        for inc in floods:
            edge = next((e for e in inc.entity_ids if e.startswith("E_")), None)
            if not edge:
                continue
            es = tr.edge_status(self.graph, state, edge)
            read_calls.append(f"traffic.edge_status({edge})")
            route = tr.shortest_route(self.graph, state, "DEPOT", "H1")
            read_calls.append("traffic.shortest_route(DEPOT->H1)")
            congestion = tr.congestion_map(self.graph, state)
            read_calls.append("traffic.congestion_map()")

            # close the flooded edge, then reroute onto a known detour corridor
            if es.get("flooded") or es.get("blocked"):
                actions.append(tr.propose_close_edge(edge, rationale=f"{es.get('depth_cm', 0)}cm water; impassable."))
            detour_pref = ["E_J5_J7", "E_J6_J7", "E_J8_H1", "E_J2_J3"]
            fast = next((eid for eid in detour_pref if eid != edge and eid not in state.flooded_edges), None)
            if fast:
                actions.append(
                    tr.propose_reroute(
                        slow_edge_id=edge,
                        fast_edge_id=fast,
                        factor=2.0,
                        rationale=f"Shift traffic off the flooded {edge} onto the {fast} corridor.",
                    )
                )
            dark_signals = [signal.id for signal in self.graph.signals if not state.signals_ok.get(signal.id, True)]
            if dark_signals:
                actions.append(tr.propose_retime_signals(dark_signals, cycle_s=45.0, rationale="Retiming remaining signals to reduce queue buildup."))

        summary = await get_callbacks().guarded_complete(self.name, f"Traffic plan for {incident_ids}")
        get_llm()._record(self.name, "propose")
        return get_llm_proposal(self, incident_ids, summary, actions, read_calls)


class EmergencyAgent(SpecialistBase):
    domain = "emergency"
    name = "emergency_agent"

    async def run(self, state: CitySnapshot, incidents: list[Incident]) -> AgentProposal:
        read_calls: list[str] = []
        actions: list[Action] = []
        incident_ids = [i.id for i in incidents]

        delays = [i for i in incidents if i.kind in ("ambulance_delayed", "flood", "substation_trip")]
        if delays:
            eta = em.ambulance_eta(self.graph, state, "A1", "H1")
            read_calls.append("emergency.ambulance_eta(A1->H1)")
            access = em.hospital_access(self.graph, state, "H1")
            read_calls.append("emergency.hospital_access(H1)")
            units = em.response_units(self.graph, state)
            read_calls.append("emergency.response_units()")

            route = tr.shortest_route(self.graph, state, "DEPOT", "H1")
            read_calls.append("traffic.shortest_route(DEPOT->H1)")
            start_edge = route["edges"][0] if route.get("edges") else "E_DEPOT_J1"
            actions.append(
                em.propose_dispatch("A1", start_edge, rationale="Dispatch on the open northern corridor.")
            )
            actions.append(
                em.propose_set_destination("A1", "H1", rationale="Route to City General.")
            )
            if self.graph.shelters:
                shelter = self.graph.shelters[0]
                actions.append(em.propose_activate_shelter(shelter.id, shelter.available, rationale=f"Activate {shelter.name} as a fallback public shelter."))

        summary = await get_callbacks().guarded_complete(self.name, f"Emergency plan for {incident_ids}")
        get_llm()._record(self.name, "propose")
        return get_llm_proposal(self, incident_ids, summary, actions, read_calls)


class WaterAgent(SpecialistBase):
    domain = "water"
    name = "water_agent"

    async def run(self, state: CitySnapshot, incidents: list[Incident]) -> AgentProposal:
        actions, reads = [], []
        targets = {entity for inc in incidents if not inc.watch_only for entity in inc.entity_ids}
        for asset in self.graph.infrastructure:
            if asset.kind != "pipeline" or asset.id not in targets:
                continue
            reads.append(f"water.failure_state({asset.id})")
            if (state.water_failures.get(asset.id) in {"pipe break", "simulated burst", "simulated probable leak"}
                    and not state.water_isolated.get(asset.id, False)):
                actions.append(Action(tool="water.isolate_pipeline", entity_ids=[asset.id],
                    params={"asset_id": asset.id}, impact=Impact.HIGH, owner=self.name,
                    rationale="Isolate the explicitly mapped failed pipeline. Water service to this segment stops; existing flooding and damage remain."))
        return get_llm_proposal(self, [i.id for i in incidents],
            "Review pipeline isolation against structured failure evidence; pressure alone is not proof.", actions, reads)


def get_llm_proposal(
    agent: SpecialistBase, incident_ids: list[str], summary: str, actions: list[Action], read_calls: list[str]
) -> AgentProposal:
    return AgentProposal(
        agent=agent.name,
        domain=agent.domain,  # type: ignore[arg-type]
        incident_ids=incident_ids,
        summary=summary,
        actions=actions,
        read_calls=read_calls,
    )


__all__ = ["PowerAgent", "TrafficAgent", "EmergencyAgent"]
