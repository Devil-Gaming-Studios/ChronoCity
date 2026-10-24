import type {
  Action,
  ActionInput,
  HospitalInfo,
  ActionLogEntry,
  Cascade,
  CityGraph,
  Compare,
  Incident,
  JointPlan,
  Metrics,
  WhatIfBranch,
} from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

export const api = {
  city: () => fetch("/api/city").then(json<CityGraph>),
  incidents: () => fetch("/api/incidents").then(json<Incident[]>),
  cascade: () => fetch("/api/incidents/cascade").then(json<Cascade>),

  /** {} when no plan exists — callers must guard on .id */
  currentPlan: () => fetch("/api/plans/current").then(json<JointPlan>),
  actionLog: () => fetch("/api/plans/action_log").then(json<ActionLogEntry[]>),
  metrics: () => fetch("/api/plans/metrics").then(json<Metrics>),
  approve: (plan_id: string, approved: boolean, note = "") =>
    post("/api/plans/approve", { plan_id, approved, note }).then((r) => r.json()),
  execute: (plan_id: string) => post("/api/plans/execute", { plan_id }).then((r) => r.json()),

  compare: () => fetch("/api/timeline/metrics").then(json<Compare>),
  whatIf: (actions: ActionInput[], label: string) =>
    post("/api/timeline/whatif", { actions, label }).then(json<WhatIfBranch>),

  startScenario: (mode: "combined" | "flood" | "trip") =>
    post(`/api/scenarios/${mode}/start`).then((r) => r.json()),
  reset: () => post("/api/scenarios/reset").then((r) => r.json()),
  importOsm: (bbox: { south: number; west: number; north: number; east: number; name?: string }) =>
    post("/api/cities/import/osm", bbox).then((r) => r.json()),
  simulationCapabilities: () => fetch("/api/simulations/capabilities").then(json<Record<string, unknown>>),
  runSimulation: (body: {
    label?: string;
    start_from?: "healthy" | "current";
    hazards: Array<Record<string, unknown>>;
    actions?: Action[];
  }) => post("/api/simulations/run", body).then(json<Record<string, unknown>>),
  hospitals: () => fetch("/api/hospitals").then(json<HospitalInfo[]>),
  hospital: (hospitalId: string) => fetch(`/api/hospitals/${encodeURIComponent(hospitalId)}`).then(json<HospitalInfo & Record<string, unknown>>),
  diagnostics: (domain: "power" | "water") => fetch(`/api/infrastructure/diagnostics?domain=${domain}`).then(json<Record<string, unknown>>),
  vehicleRoute: (body: { vehicle_type: "firetruck" | "police" | "ambulance"; origin?: string; destination_node?: string; hospital_id?: string; incident_edge_id?: string }) =>
    post("/api/routes/vehicles", body).then(json<Record<string, unknown>>),
  runCommand: (body: { text: string; start_from?: "healthy" | "current"; selected_entity_id?: string; selected_entity_type?: string }) =>
    post("/api/commands/run", body).then(json<Record<string, unknown>>),
};
