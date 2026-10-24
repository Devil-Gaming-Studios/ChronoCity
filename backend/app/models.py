from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------- enums


class Impact(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    VERIFIED = "VERIFIED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ComponentType(str, Enum):
    NODE = "NODE"
    EDGE = "EDGE"
    SUBSTATION = "SUBSTATION"
    FEEDER = "FEEDER"
    SIGNAL = "SIGNAL"
    HOSPITAL = "HOSPITAL"
    UNDERPASS = "UNDERPASS"


# ---------------------------------------------------------------- city


class Node(BaseModel):
    id: str
    kind: Literal["junction", "substation", "hospital", "depot", "underpass", "shelter"] = "junction"
    x: float = 0.0
    y: float = 0.0
    zone: str = "Z0"
    name: str = ""
    lat: float | None = None
    lon: float | None = None
    osm_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    src: str
    dst: str
    length_m: float = 100.0
    lanes: int = 1
    free_flow_kph: float = 40.0
    kind: Literal["road", "underpass", "feeder"] = "road"
    name: str = ""
    osm_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Building(BaseModel):
    """A lightweight extrudable building footprint in local city coordinates."""

    id: str
    name: str = ""
    kind: str = "building"
    footprint: list[tuple[float, float]] = Field(default_factory=list)
    height_m: float = 8.0
    levels: int | None = None
    lat: float | None = None
    lon: float | None = None
    osm_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class InfrastructureAsset(BaseModel):
    """Imported infrastructure that is available for future domain simulators."""

    id: str
    kind: str
    geometry: list[tuple[float, float]] = Field(default_factory=list)
    name: str = ""
    osm_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Substation(BaseModel):
    id: str
    node_id: str
    feeders: list[str] = Field(default_factory=list)
    capacity_mw: float = 40.0
    generation_mw: float = 30.0


class Feeder(BaseModel):
    id: str
    substation_id: str
    serves: list[str] = Field(default_factory=list)  # signal / junction ids


class Signal(BaseModel):
    id: str
    node_id: str
    feeder_id: str


class HospitalDepartment(BaseModel):
    id: str
    name: str
    total_beds: int = 0
    available_beds: int = 0
    status: Literal["open", "limited", "closed"] = "open"


class Hospital(BaseModel):
    id: str
    node_id: str
    name: str = "General Hospital"
    departments: list[HospitalDepartment] = Field(default_factory=list)


class Shelter(BaseModel):
    id: str
    node_id: str
    name: str = "Emergency Shelter"
    capacity: int = 0
    available: int = 0
    active: bool = False


class Underpass(BaseModel):
    id: str
    edge_id: str
    name: str = ""


class CityGraph(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    substations: list[Substation] = Field(default_factory=list)
    feeders: list[Feeder] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    hospitals: list[Hospital] = Field(default_factory=list)
    shelters: list[Shelter] = Field(default_factory=list)
    underpasses: list[Underpass] = Field(default_factory=list)
    buildings: list[Building] = Field(default_factory=list)
    infrastructure: list[InfrastructureAsset] = Field(default_factory=list)
    source: str = "demo"
    source_ref: str = ""
    name: str = "ChronoTwin Demo City"
    bounds: dict[str, float] = Field(default_factory=dict)
    attribution: str = ""


# ---------------------------------------------------------------- telemetry


class SensorReading(BaseModel):
    id: str = Field(default_factory=_id)
    sensor_id: str
    zone: str = "Z0"
    kind: Literal["water_level_cm", "power_draw_kw", "queue_len", "signal_ok", "gps_speed_kph"] = "water_level_cm"
    value: float = 0.0
    ts: float = Field(default_factory=_now)
    trust: float = 1.0


class CitizenReport(BaseModel):
    id: str = Field(default_factory=_id)
    category: Literal["flooding", "blackout", "gridlock", "accident", "other"] = "other"
    lat: float = 0.0
    lon: float = 0.0
    zone: str = "Z0"
    text: str = ""  # stored, NEVER sent to a model
    reporter_trust: float = 0.5
    ts: float = Field(default_factory=_now)


class ValidatedSignal(BaseModel):
    """A reduced, code-produced signal. This is the ONLY thing agents ever see."""

    id: str = Field(default_factory=_id)
    source: Literal["sensor", "report"] = "sensor"
    zone: str = "Z0"
    kind: str = "water_level_cm"
    value: float = 0.0
    severity: IncidentSeverity = IncidentSeverity.INFO
    entity_ids: list[str] = Field(default_factory=list)
    trust: float = 1.0
    lat: float | None = None
    lon: float | None = None
    ts: float = Field(default_factory=_now)


class Anomaly(BaseModel):
    id: str = Field(default_factory=_id)
    detector: str = "threshold"
    zone: str = "Z0"
    kind: str = "water_level_cm"
    entity_ids: list[str] = Field(default_factory=list)
    severity: IncidentSeverity = IncidentSeverity.WARNING
    zscore: float = 0.0
    ts: float = Field(default_factory=_now)


class Incident(BaseModel):
    id: str = Field(default_factory=_id)
    kind: Literal["flood", "substation_trip", "signal_dark", "gridlock", "ambulance_delayed", "pipe_leak"] = "flood"
    severity: IncidentSeverity = IncidentSeverity.WARNING
    zone: str = "Z0"
    entity_ids: list[str] = Field(default_factory=list)
    title: str = ""
    detail: str = ""
    priority: int = 5  # 1 highest
    trust: float = 1.0
    dedupe_key: str = ""
    created_ts: float = Field(default_factory=_now)
    resolved: bool = False
    evidence_sources: list[str] = Field(default_factory=list)
    watch_only: bool = False


# ---------------------------------------------------------------- actions & plans


class Action(BaseModel):
    """A mutating proposal. Data, never an immediate command."""

    id: str = Field(default_factory=_id)
    tool: str  # e.g. "power.reroute_feeder", "traffic.reroute", "emergency.dispatch"
    entity_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    impact: Impact = Impact.MEDIUM
    rationale: str = ""
    owner: str = ""  # agent name


class AgentProposal(BaseModel):
    id: str = Field(default_factory=_id)
    agent: str
    domain: Literal["power", "traffic", "emergency"] = "traffic"
    incident_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    actions: list[Action] = Field(default_factory=list)
    read_calls: list[str] = Field(default_factory=list)  # proof it used read tools first
    created_ts: float = Field(default_factory=_now)


class Conflict(BaseModel):
    id: str = Field(default_factory=_id)
    kind: Literal["resource", "contradiction", "ordering"] = "contradiction"
    a_action_id: str
    b_action_id: str
    description: str


class JointPlan(BaseModel):
    id: str = Field(default_factory=_id)
    incident_ids: list[str] = Field(default_factory=list)
    proposals: list[AgentProposal] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    resolution: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    version: int = 1
    critic_feedback: str = ""
    needs_revision: bool = False
    dropped_action_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    created_ts: float = Field(default_factory=_now)


class ApprovalRecord(BaseModel):
    id: str = Field(default_factory=_id)
    plan_id: str
    approver: str = "operator"
    approved: bool = False
    note: str = ""
    ts: float = Field(default_factory=_now)


class ActionLogEntry(BaseModel):
    id: str = Field(default_factory=_id)
    plan_id: str = ""
    action_id: str = ""
    tool: str
    phase: Literal["propose", "verify", "approve", "execute"] = "propose"
    actor: str = "agent"
    impact: Impact = Impact.MEDIUM
    ok: bool = True
    detail: str = ""
    ts: float = Field(default_factory=_now)


# ---------------------------------------------------------------- simulation


class SimulationResult(BaseModel):
    plan_id: str
    passed: bool
    score: float = 0.0
    travel_time_s: float = 0.0
    baseline_travel_time_s: float = 0.0
    dark_junctions: int = 0
    contained_hops: int = 0
    jammed_arterials: int = 0
    blocked_edges: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    final_state: dict[str, Any] | None = None  # post-plan state (sim only)


class CitySnapshot(BaseModel):
    model_config = {"allow_inf_nan": False}
    t: float = 0.0
    powered: dict[str, bool] = Field(default_factory=dict)      # feeder_id -> on
    signals_ok: dict[str, bool] = Field(default_factory=dict)   # signal_id -> ok
    signal_timing_s: dict[str, float] = Field(default_factory=dict) # signal_id -> cycle/retiming seconds
    flooded_edges: dict[str, float] = Field(default_factory=dict)  # edge_id -> depth_cm
    closed_edges: dict[str, bool] = Field(default_factory=dict)    # edge_id -> closed
    edge_factor: dict[str, float] = Field(default_factory=dict)    # edge_id -> reroute factor
    edge_travel_s: dict[str, float] = Field(default_factory=dict)  # edge_id -> seconds
    power_load_mw: dict[str, float] = Field(default_factory=dict)  # substation_id -> load
    power_generation_mw: dict[str, float] = Field(default_factory=dict)  # substation_id -> generated output
    failed_assets: dict[str, str] = Field(default_factory=dict)   # asset_id -> failure reason
    water_pressure_kpa: dict[str, float] = Field(default_factory=dict)
    water_failures: dict[str, str] = Field(default_factory=dict)
    vehicles: dict[str, str] = Field(default_factory=dict)      # vehicle_id -> edge_id
    ambulances: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shelters: dict[str, dict[str, Any]] = Field(default_factory=dict)
