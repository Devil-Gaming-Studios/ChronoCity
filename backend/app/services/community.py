from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Any, Literal

from ..models import CityGraph, CitySnapshot, Incident
from ..sim.state import pipeline_affected_edges

Category = Literal["flood", "blackout", "pipe_leak", "traffic"]
MAX_BATCHES = 200
MAX_INCIDENTS = 400
MAX_EVENTS = 500
MAX_EVIDENCE_PER_BATCH = 50


def known_zones(graph: CityGraph) -> set[str]:
    return {node.zone for node in graph.nodes} | {
        asset.tags["zone"] for asset in graph.infrastructure if asset.tags.get("zone")
    }


def matching_evidence(graph: CityGraph, state: CitySnapshot, zone: str, category: Category) -> list[Incident]:
    """Reduce trusted simulator facts, never complaint text/count or cached travel."""
    node_zones = {node.id: node.zone for node in graph.nodes}
    roads = [edge for edge in graph.edges if edge.kind in {"road", "underpass"}
             and zone in {node_zones.get(edge.src), node_zones.get(edge.dst)}]
    out: list[Incident] = []

    def add(kind: Literal["flood", "gridlock", "substation_trip", "pipe_leak"],
            entities: list[str], title: str, source: str) -> None:
        out.append(Incident(
            kind=kind, zone=zone, entity_ids=entities, title=title,
            detail="Cross-checked against structured simulation state; report text is excluded.",
            dedupe_key=f"community:{category}:{zone}:{':'.join(entities)}",
            evidence_sources=["simulation", source], trust=1.0, watch_only=False,
        ))

    if category == "flood":
        for edge in roads:
            if state.flooded_edges.get(edge.id, 0) > 0:
                add("flood", [edge.id], "Road flooding verified in simulation", "flooded_edges")
    elif category == "traffic":
        dark_nodes = {sig.node_id for sig in graph.signals if state.signals_ok.get(sig.id) is False}
        for edge in roads:
            if (state.edge_factor.get(edge.id, 1) >= 1.5 or state.closed_edges.get(edge.id, False)
                    or state.flooded_edges.get(edge.id, 0) > 0 or {edge.src, edge.dst} & dark_nodes):
                add("gridlock", [edge.id], "Road disruption verified in simulation", "road_state")
    elif category == "blackout":
        for sub in graph.substations:
            off = {fid for fid in sub.feeders if state.powered.get(fid) is False}
            # A dark signal alone does not prove a power outage.
            served_zones = {node_zones.get(sig.node_id) for sig in graph.signals if sig.feeder_id in off}
            if off and (zone in served_zones or node_zones.get(sub.node_id) == zone):
                add("substation_trip", [sub.id], "Power supply loss verified in simulation", "powered")
    elif category == "pipe_leak":
        for asset in graph.infrastructure:
            if asset.kind != "pipeline" or asset.tags.get("zone") != zone:
                continue
            # Low pressure is a warning, not independent evidence of a leak.
            if state.water_failures.get(asset.id) not in {"pipe break", "simulated burst", "simulated probable leak"}:
                continue
            flooded = [eid for eid in pipeline_affected_edges(graph, asset.id) if state.flooded_edges.get(eid, 0) > 0]
            add("flood" if flooded else "pipe_leak", [*flooded, asset.id],
                "Pipeline failure with road flooding" if flooded else "Pipeline failure verified in simulation",
                "water_failures")
    return out[:MAX_EVIDENCE_PER_BATCH]


class CommunityState:
    """Bounded, process-local audit tied to both city and live runtime identity."""

    def __init__(self, graph: CityGraph, orchestrator: Any) -> None:
        self.graph = graph
        self.orchestrator = orchestrator
        self.batches: deque[dict[str, Any]] = deque(maxlen=MAX_BATCHES)
        self.incidents: dict[str, dict[str, Any]] = {}
        self.events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self.plan_lock = asyncio.Lock()

    def event(self, stage: str, **data: Any) -> dict[str, Any]:
        item = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "stage": stage, **data}
        if self.orchestrator.audit:
            self.orchestrator.audit("community_event", item, scope=data.get("source", "live"))
        self.events.append(item)
        return item

    def submit(self, *, zone: str, category: Category, text: str, count: int,
               state: CitySnapshot, preview: bool) -> dict[str, Any]:
        batch_id = uuid.uuid4().hex[:12]
        source = "preview" if preview else "live"
        events = [self.event("received", batch_id=batch_id, count=count, source=source),
                  self.event("validated", batch_id=batch_id, zone=zone, category=category)]
        matches = matching_evidence(self.graph, state, zone, category)
        records = []
        for incident in matches:
            # Keep active evidence stable across repeated influx batches.
            existing = next((record for record in self.incidents.values()
                             if record["source"] == source and record["category"] == category
                             and record["incident"].dedupe_key == incident.dedupe_key
                             and record["status"] == "verified"), None)
            record = existing or {"incident": incident, "category": category, "source": source,
                                  "status": "verified", "plan_id": None}
            self.incidents[record["incident"].id] = record
            records.append(self.serialize(record))
        while len(self.incidents) > MAX_INCIDENTS:
            self.incidents.pop(next(iter(self.incidents)))
        verified = bool(records)
        batch = {
            "id": batch_id, "ts": time.time(), "zone": zone, "category": category,
            "text": text, "text_trust": "untrusted_display_only", "count": count, "source": source,
            "verification_status": "verified" if verified else "watch_only",
            "incident_ids": [record["id"] for record in records],
            "explanation": "Matching simulation evidence found." if verified else
                "Reports alone cannot verify an incident, regardless of complaint count.",
        }
        self.batches.append(batch)
        events.append(self.event("verified" if verified else "watch_only", batch_id=batch_id,
                                 incident_ids=batch["incident_ids"], source=source))
        return {"ok": True, "batch": batch, "incidents": records, "events": events}

    @staticmethod
    def serialize(record: dict[str, Any]) -> dict[str, Any]:
        return {**record["incident"].model_dump(mode="json"),
                "category": record["category"], "source": record["source"], "status": record["status"],
                "eligible_for_plan": record["source"] == "live" and record["status"] == "verified",
                "plan_id": record["plan_id"]}

    def snapshot(self) -> dict[str, Any]:
        return {"batches": list(self.batches), "incidents": [self.serialize(r) for r in self.incidents.values()],
                "events": list(self.events),
                "limits": {"batches": MAX_BATCHES, "incidents": MAX_INCIDENTS, "events": MAX_EVENTS,
                           "count_per_batch": 100, "evidence_per_batch": MAX_EVIDENCE_PER_BATCH}}


def get_community(app: Any) -> CommunityState:
    current = getattr(app.state, "community", None)
    if (not isinstance(current, CommunityState) or current.graph is not app.state.graph
            or current.orchestrator is not app.state.orchestrator):
        current = CommunityState(app.state.graph, app.state.orchestrator)
        app.state.community = current
    return current
