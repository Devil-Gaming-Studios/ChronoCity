from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Any, Literal

from ..models import CityGraph, CitySnapshot, Incident, IncidentSeverity
from ..sim.state import pipeline_affected_edges

Category = Literal["flood", "blackout", "pipe_leak", "traffic"]
ComplaintTargetType = Literal["road", "residential_building"]
MAX_BATCHES = 200
MAX_INCIDENTS = 400
MAX_EVENTS = 500
MAX_EVIDENCE_PER_BATCH = 50
COMPLAINT_SURGE_THRESHOLD = 50


def known_zones(graph: CityGraph) -> set[str]:
    return {node.zone for node in graph.nodes} | {
        asset.tags["zone"] for asset in graph.infrastructure if asset.tags.get("zone")
    } | {
        building.tags["zone"] for building in graph.buildings if building.tags.get("zone")
    }


def resolve_complaint_target(
    graph: CityGraph,
    target_id: str | None,
    target_type: ComplaintTargetType | None,
) -> dict[str, Any] | None:
    """Validate a map-selected complaint target and return its structured scope."""
    if target_id is None and target_type is None:
        return None
    if not target_id or not target_type:
        raise ValueError("target_id and target_type must be provided together")
    if target_type == "road":
        edge = next((item for item in graph.edges if item.id == target_id and item.kind in {"road", "underpass"}), None)
        if edge is None:
            raise ValueError("selected road is not part of the active city")
        node_zones = {node.id: node.zone for node in graph.nodes}
        return {"id": edge.id, "type": target_type, "label": edge.name or edge.id,
                "zone": node_zones.get(edge.src) or node_zones.get(edge.dst)}

    building = next((item for item in graph.buildings if item.id == target_id), None)
    if building is None:
        raise ValueError("selected residential building is not part of the active city")
    kind = (building.kind or building.tags.get("building", "")).lower()
    residential_kinds = {"residential", "house", "apartments", "detached", "semidetached_house", "terrace", "yes"}
    if kind not in residential_kinds and building.tags.get("building", "").lower() not in residential_kinds:
        raise ValueError("selected building must be residential")
    zone = building.tags.get("zone") or ("OSM" if graph.source == "osm" else None)
    return {"id": building.id, "type": target_type, "label": building.name or building.id, "zone": zone}


def matching_evidence(
    graph: CityGraph,
    state: CitySnapshot,
    zone: str,
    category: Category,
    target: dict[str, Any] | None = None,
) -> list[Incident]:
    """Reduce trusted simulator facts, never complaint text/count or cached travel."""
    node_zones = {node.id: node.zone for node in graph.nodes}
    roads = [edge for edge in graph.edges if edge.kind in {"road", "underpass"}
             and zone in {node_zones.get(edge.src), node_zones.get(edge.dst)}
             and (not target or target["type"] != "road" or edge.id == target["id"])]
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


def inferred_complaint_evidence(
    graph: CityGraph,
    zone: str,
    category: Category,
    target: dict[str, Any] | None = None,
) -> list[Incident]:
    """Create a bounded, region-scoped simulation incident from a complaint surge.

    This intentionally uses only the selected structured category and region. Resident
    text is never inspected, and the returned incident is still only a proposal input;
    the live twin changes only after the normal operator approval and execution flow.
    """
    node_zones = {node.id: node.zone for node in graph.nodes}
    roads = [edge for edge in graph.edges if edge.kind in {"road", "underpass"}
             and zone in {node_zones.get(edge.src), node_zones.get(edge.dst)}
             and (not target or target["type"] != "road" or edge.id == target["id"])]

    if category in {"flood", "traffic"}:
        if not roads:
            return []
        edge = roads[0]
        kind = "flood" if category == "flood" else "gridlock"
        title = "Likely flooding inferred from complaint surge" if category == "flood" else "Likely road disruption inferred from complaint surge"
        target_note = f" Target selected: {target['label']} ({target['type']})." if target else ""
        return [Incident(
            kind=kind,
            zone=zone,
            entity_ids=[edge.id],
            title=title,
            detail="Simulation inference from an overwhelming structured complaint surge; no sensor reading was required." + target_note,
            dedupe_key=f"community:{category}:{zone}:{target['id'] if target else 'inferred'}",
            evidence_sources=["community_reports"],
            trust=0.7,
            severity=IncidentSeverity.WARNING,
            watch_only=False,
        )]

    if category == "pipe_leak":
        pipelines = [asset for asset in graph.infrastructure
                     if asset.kind == "pipeline" and asset.tags.get("zone") == zone]
        if not pipelines:
            return []
        asset = pipelines[0]
        return [Incident(
            kind="pipe_leak",
            zone=zone,
            entity_ids=[asset.id],
            title="Likely pipeline leak inferred from complaint surge",
            detail="Simulation inference from an overwhelming structured complaint surge; the mapped pipeline is the proposed target.",
            dedupe_key=f"community:{category}:{zone}:inferred",
            evidence_sources=["community_reports"],
            trust=0.7,
            severity=IncidentSeverity.WARNING,
            watch_only=False,
        )]

    # A blackout is scoped to a substation that serves at least one signal in the
    # selected region. This avoids inventing an electrical asset for an unmapped zone.
    if category == "blackout":
        for sub in graph.substations:
            served_zones = {
                node_zones.get(signal.node_id)
                for signal in graph.signals
                if signal.feeder_id in sub.feeders
            }
            if zone == node_zones.get(sub.node_id) or zone in served_zones:
                return [Incident(
                    kind="substation_trip",
                    zone=zone,
                    entity_ids=[sub.id],
                    title="Likely power outage inferred from complaint surge",
                    detail="Simulation inference from an overwhelming structured complaint surge; no power sensor reading was required.",
                    dedupe_key=f"community:{category}:{zone}:inferred",
                    evidence_sources=["community_reports"],
                    trust=0.7,
                    severity=IncidentSeverity.WARNING,
                    watch_only=False,
                )]
    return []


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
               state: CitySnapshot, preview: bool, target: dict[str, Any] | None = None) -> dict[str, Any]:
        batch_id = uuid.uuid4().hex[:12]
        source = "preview" if preview else "live"
        events = [self.event("received", batch_id=batch_id, count=count, source=source),
                  self.event("validated", batch_id=batch_id, zone=zone, category=category)]
        matches = matching_evidence(self.graph, state, zone, category, target)
        inferred = False
        if not matches and not preview and count >= COMPLAINT_SURGE_THRESHOLD:
            matches = inferred_complaint_evidence(self.graph, zone, category, target)
            inferred = bool(matches)
        records = []
        for incident in matches:
            # Keep active evidence stable across repeated influx batches.
            existing = next((record for record in self.incidents.values()
                             if record["source"] == source and record["category"] == category
                             and record["incident"].dedupe_key == incident.dedupe_key
                             and record["status"] in {"verified", "inferred", "planned"}), None)
            record = existing or {"incident": incident, "category": category, "source": source,
                                  "status": "inferred" if inferred else "verified", "plan_id": None,
                                  "count": count}
            self.incidents[record["incident"].id] = record
            records.append(self.serialize(record))
        while len(self.incidents) > MAX_INCIDENTS:
            self.incidents.pop(next(iter(self.incidents)))
        verified = bool(records)
        batch = {
            "id": batch_id, "ts": time.time(), "zone": zone, "category": category,
            "text": text, "text_trust": "untrusted_display_only", "count": count, "source": source,
            "target": target,
            "verification_status": "inferred" if inferred else "verified" if verified else "watch_only",
            "incident_ids": [record["id"] for record in records],
            "explanation": "Matching simulation evidence found." if verified and not inferred else
            "An overwhelming complaint surge created a region-scoped simulation inference; operator approval is still required." if inferred else
            "Reports alone cannot verify an incident below the complaint-surge threshold.",
        }
        self.batches.append(batch)
        events.append(self.event("inferred" if inferred else "verified" if verified else "watch_only", batch_id=batch_id,
                                 incident_ids=batch["incident_ids"], source=source))
        return {"ok": True, "batch": batch, "incidents": records, "events": events}

    @staticmethod
    def serialize(record: dict[str, Any]) -> dict[str, Any]:
        return {**record["incident"].model_dump(mode="json"),
                "category": record["category"], "source": record["source"], "status": record["status"],
                "eligible_for_plan": record["source"] == "live" and record["status"] in {"verified", "inferred"},
                "plan_id": record["plan_id"]}

    def snapshot(self) -> dict[str, Any]:
        return {"batches": list(self.batches), "incidents": [self.serialize(r) for r in self.incidents.values()],
                "events": list(self.events),
                "limits": {"batches": MAX_BATCHES, "incidents": MAX_INCIDENTS, "events": MAX_EVENTS,
                           "count_per_batch": 100, "evidence_per_batch": MAX_EVIDENCE_PER_BATCH,
                           "inference_threshold": COMPLAINT_SURGE_THRESHOLD}}


def get_community(app: Any) -> CommunityState:
    current = getattr(app.state, "community", None)
    if (not isinstance(current, CommunityState) or current.graph is not app.state.graph
            or current.orchestrator is not app.state.orchestrator):
        current = CommunityState(app.state.graph, app.state.orchestrator)
        app.state.community = current
    return current
