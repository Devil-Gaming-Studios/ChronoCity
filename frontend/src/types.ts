// Accurate mirrors of the FastAPI response shapes (backend/app/api/*).

export interface CityNode {
  id: string;
  kind: "junction" | "substation" | "hospital" | "depot" | "underpass" | "shelter";
  x: number;
  y: number;
  zone: string;
  name: string;
}

export interface CityEdge {
  id: string;
  src: string;
  dst: string;
  length_m: number;
  lanes: number;
  free_flow_kph: number;
  kind: "road" | "underpass" | "feeder";
  name?: string;
  tags?: Record<string, string>;
}

export interface HospitalDepartment {
  id: string;
  name: string;
  total_beds: number;
  available_beds: number;
  status: "open" | "limited" | "closed";
}

export interface HospitalInfo {
  id: string;
  node_id: string;
  name: string;
  departments: HospitalDepartment[];
}

export interface MapSelection {
  id: string;
  type: string;
  label: string;
}

export interface RouteRequest {
  vehicle_type: "ambulance" | "firetruck" | "police";
  origin: string;
  destination_node: string;
}

export interface PowerDiagnostics {
  domain: string;
  stations: Array<{
    substation_id: string;
    generation_mw: number;
    output_mw: number;
    load_mw: number;
    capacity_mw: number;
    status: string;
  }>;
  affected_nodes: string[];
  affected_zones: string[];
  coverage_note: string;
  model_note: string;
}

export interface CommunityState {
  batches: Array<Record<string, unknown>>;
  incidents: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  limits?: Record<string, number>;
}

export interface CityBuilding {
  id: string;
  name: string;
  kind: string;
  footprint: [number, number][];
  height_m: number;
  levels?: number | null;
  tags?: Record<string, string>;
}

export interface CityGraph {
  nodes: CityNode[];
  edges: CityEdge[];
  substations: { id: string; node_id: string; feeders: string[]; capacity_mw: number; generation_mw?: number }[];
  feeders: { id: string; substation_id: string; serves: string[] }[];
  signals: { id: string; node_id: string; feeder_id: string }[];
  hospitals: HospitalInfo[];
  shelters?: { id: string; node_id: string; name: string; capacity: number; available: number; active: boolean }[];
  underpasses: { id: string; edge_id: string; name: string }[];
  buildings?: CityBuilding[];
  infrastructure?: { id: string; kind: string; geometry: [number, number][]; name: string }[];
  source?: string;
  source_ref?: string;
  name?: string;
  bounds?: Record<string, number>;
  attribution?: string;
}

export interface CitySnapshot {
  t: number;
  powered: Record<string, boolean>;
  signals_ok: Record<string, boolean>;
  flooded_edges: Record<string, number>;
  closed_edges: Record<string, boolean>;
  edge_factor: Record<string, number>;
  edge_travel_s: Record<string, number>;
  power_load_mw: Record<string, number>;
  power_generation_mw: Record<string, number>;
  failed_assets: Record<string, string>;
  vehicles: Record<string, string>;
  ambulances: Record<string, Record<string, unknown>>;
  shelters?: Record<string, Record<string, unknown>>;
}

export type Impact = "LOW" | "MEDIUM" | "HIGH";

export interface Action {
  id: string;
  tool: string;
  entity_ids: string[];
  params: Record<string, unknown>;
  impact: Impact;
  rationale: string;
  owner: string;
}

/** Client-side partial for actions sent to the what-if endpoint (only tool is required). */
export type ActionInput = Partial<Action> & { tool: string };

export interface Conflict {
  id: string;
  kind: "resource" | "contradiction" | "ordering";
  a_action_id: string;
  b_action_id: string;
  description: string;
}

export interface Proposal {
  id?: string;
  agent: string;
  domain: "power" | "traffic" | "emergency";
  incident_ids?: string[];
  summary: string;
  actions: Action[] | number; // /plans/current gives full actions; /plans gives a count
  read_calls: string[];
  created_ts?: number;
}

/** GET /api/plans/current ({} when there is no plan). */
export interface JointPlan {
  id: string;
  status: string; // PlanStatus
  version: number;
  actions: Action[];
  conflicts: Conflict[];
  resolution: string;
  critic_feedback: string;
  metrics: Record<string, number>;
  proposals: Proposal[];
  needs_high_approval?: boolean;
  dropped_action_ids?: string[];
  needs_revision?: boolean;
}

export interface ActionLogEntry {
  id: string;
  plan_id: string;
  action_id: string;
  tool: string;
  phase: "propose" | "verify" | "approve" | "execute";
  actor: string;
  impact: Impact;
  ok: boolean;
  detail: string;
  ts: number;
}

export interface Incident {
  id: string;
  kind: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  zone: string;
  title: string;
  detail: string;
  priority: number;
  trust: number;
  resolved: boolean;
  entity_ids: string[];
  created_ts: number;
}

export interface CascadeHop {
  hop: number;
  entities: string[];
}

/** GET /api/incidents/cascade */
export interface Cascade {
  roots: string[];
  hops: CascadeHop[];
  contained_hops: number;
  affected: string[];
}

/** GET /api/plans/metrics */
export interface Metrics {
  llm_calls: number;
  llm_budget: number;
  llm_mode: string;
  incidents: number;
  plans: number;
  plans_verified: number;
  plans_rejected: number;
  approvals: number;
  actions_executed: number;
  readings_processed: number;
}

/** GET /api/timeline/metrics */
export interface Compare {
  ambulance_eta_baseline_s: number | null;
  ambulance_eta_now_s: number | null;
  dark_signals_baseline: number;
  dark_signals_now: number;
  plan_metrics: Record<string, number>;
  sim_notes: string;
}

/** POST /api/timeline/whatif response */
export interface WhatIfBranch {
  label: string;
  actions: Action[];
  result: {
    plan_id: string;
    passed: boolean;
    score: number;
    travel_time_s: number;
    baseline_travel_time_s: number;
    dark_junctions: number;
    contained_hops: number;
    blocked_edges: string[];
    notes: string[];
  };
  after_state: CitySnapshot | null;
}

/** A normalized WebSocket frame. Payload fields sit at the top level. */
export interface ChronoEvent {
  id: string;
  ts: number; // receive time (seconds)
  kind: string;
  [k: string]: unknown;
}
