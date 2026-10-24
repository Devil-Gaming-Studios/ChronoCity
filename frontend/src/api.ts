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
  CitySnapshot,
  PowerDiagnostics,
  CommunityState,
} from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.clone().json()) as { detail?: unknown; error?: unknown };
      detail = String(body.detail ?? body.error ?? "");
    } catch {
      /* use the HTTP status when the server did not return JSON */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return (await res.json()) as T;
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = 15000): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The command timed out after 15 seconds. Check that the backend is running and try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
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
    post("/api/plans/approve", { plan_id, approved, note }).then(json<Record<string, unknown>>),
  execute: (plan_id: string) => post("/api/plans/execute", { plan_id }).then(json<Record<string, unknown>>),
  editPlan: (plan_id: string, remove_action_ids: string[]) => post("/api/plans/edit", { plan_id, remove_action_ids }).then(json<Record<string, unknown>>),

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
    base_state?: CitySnapshot | null;
  }) => post("/api/simulations/run", body).then(json<Record<string, unknown>>),
  hospitals: () => fetch("/api/hospitals").then(json<HospitalInfo[]>),
  hospital: (hospitalId: string) => fetch(`/api/hospitals/${encodeURIComponent(hospitalId)}`).then(json<HospitalInfo & Record<string, unknown>>),
  diagnostics: (domain: "power" | "water") => fetch(`/api/infrastructure/diagnostics?domain=${domain}`).then(json<Record<string, unknown>>),
  vehicleRoute: (body: { vehicle_type: "firetruck" | "police" | "ambulance"; origin?: string; destination_node?: string; hospital_id?: string; incident_edge_id?: string; state?: CitySnapshot | null }) =>
    post("/api/routes/vehicles", body).then(json<Record<string, unknown>>),
  previewPower: (state: CitySnapshot) => post("/api/infrastructure/diagnostics/preview", { state }).then(json<PowerDiagnostics>),
  communityState: () => fetch("/api/community/state").then(json<CommunityState>),
  submitComplaint: (body: { zone: string; category: "flood" | "blackout" | "pipe_leak" | "traffic"; text: string; count: number; state?: CitySnapshot | null }) => post("/api/community/complaints", body).then(json<Record<string, unknown>>),
  pipelinePreview: (body: { asset_id: string; pressure_kpa: number; base_state?: CitySnapshot | null }) => post("/api/community/pipeline-preview", body).then(json<Record<string, unknown>>),
  planCommunity: (incident_ids: string[]) => post("/api/community/plan", { incident_ids }).then(json<Record<string, unknown>>),
  runCommand: (body: { text: string; start_from?: "healthy" | "current"; selected_entity_id?: string; selected_entity_ids?: string[]; selected_entity_type?: string; base_state?: CitySnapshot | null }) =>
    fetchWithTimeout("/api/commands/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<Record<string, unknown>>),
};
