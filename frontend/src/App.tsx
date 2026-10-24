import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useChronoSocket } from "./useChronoSocket";
import type {
  Cascade,
  ChronoEvent,
  CityGraph,
  CitySnapshot,
  Compare,
  Incident,
  JointPlan,
  Metrics,
  HospitalInfo,
  MapSelection,
  RouteRequest,
  PowerDiagnostics,
} from "./types";
import TwinScene, { type ViewMode } from "./components/TwinScene";
import IncidentPanel from "./components/IncidentPanel";
import ChatterPanel from "./components/ChatterPanel";
import TimelineBar from "./components/TimelineBar";
import ControlPanel from "./components/ControlPanel";
import SimulationPanel from "./components/SimulationPanel";
import ComplaintsPanel from "./components/ComplaintsPanel";
import OperatorDashboard from "./components/OperatorDashboard";
import type { CommunityState } from "./types";

export default function App() {
  const [graph, setGraph] = useState<CityGraph | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [cascade, setCascade] = useState<Cascade | null>(null);
  const [plan, setPlan] = useState<JointPlan | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [compare, setCompare] = useState<Compare | null>(null);
  const [beforeState, setBeforeState] = useState<CitySnapshot | null>(null);
  const [whatIfState, setWhatIfState] = useState<CitySnapshot | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("present");
  const [running, setRunning] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  const [verifiedAt, setVerifiedAt] = useState<number | null>(null);
  const [criticIterations, setCriticIterations] = useState(0);
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const [selectedHospital, setSelectedHospital] = useState<HospitalInfo | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [commandText, setCommandText] = useState("");
  const [commandBusy, setCommandBusy] = useState(false);
  const [commandResult, setCommandResult] = useState<Record<string, unknown> | null>(null);
  const [routeResponse, setRouteResponse] = useState<{ key: string; result: Record<string, unknown> } | null>(null);
  const [powerResponse, setPowerResponse] = useState<{ key: string; result: PowerDiagnostics } | null>(null);
  const [routeConfig, setRouteConfig] = useState<RouteRequest | null>(null);
  const [selectedItems, setSelectedItems] = useState<MapSelection[]>([]);
  const [layers, setLayers] = useState({ power: true, traffic: true, emergency: true, reports: true });
  const [surface, setSurface] = useState<"city" | "operator">("city");
  const [community, setCommunity] = useState<CommunityState | null>(null);

  const refreshIncidents = useCallback(async () => {
    try {
      setIncidents(await api.incidents());
      setCascade(await api.cascade());
    } catch {
      /* backend offline */
    }
  }, []);

  const refreshPlan = useCallback(async () => {
    try {
      const p = await api.currentPlan();
      setPlan(p && p.id ? p : null);
    } catch {
      /* backend offline */
    }
  }, []);

  const refreshMetrics = useCallback(async () => {
    try {
      setMetrics(await api.metrics());
      setCompare(await api.compare());
    } catch {
      /* backend offline */
    }
  }, []);

  const refreshAll = useCallback(() => {
    void refreshIncidents();
    void refreshPlan();
    void refreshMetrics();
    void api.communityState().then(setCommunity).catch(() => undefined);
  }, [refreshIncidents, refreshPlan, refreshMetrics]);

  // ---- WebSocket-driven updates ----
  const onEvent = useCallback(
    (e: ChronoEvent) => {
      switch (e.kind) {
        case "state_delta":
        case "state": {
          const scenario = e.scenario as string | undefined;
          const st = e.state as CitySnapshot | undefined;
          // the first state broadcast of a scenario is the "before" picture
          if (scenario && scenario !== "reset" && st) {
            setBeforeState((prev) => prev ?? st ?? null);
          }
          break;
        }
        case "critic":
          setCriticIterations((p) => Math.max(p, Number(e.iteration ?? 0) + 1));
          break;
        case "verified":
          setVerifiedAt(Date.now());
          setRunning(false);
          refreshAll();
          break;
        case "city_loaded":
          api.city().then(setGraph).catch(() => undefined);
          refreshIncidents();
          refreshMetrics();
          break;
        case "executed":
        case "plan_edited":
        case "manual_plan":
          refreshAll();
          break;
        case "incident":
          refreshIncidents();
          refreshMetrics();
          break;
        case "approval":
          refreshPlan();
          refreshMetrics();
          break;
        case "community":
          void api.communityState().then(setCommunity).catch(() => undefined);
          refreshPlan();
          refreshMetrics();
          break;
        case "command_response":
          setCommandResult({
            answer: e.answer,
            explanation: Array.isArray(e.explanation) ? e.explanation : [],
            affected_nodes: e.affected_nodes,
            affected_assets: e.affected_assets,
          });
          break;
        case "command_error":
        case "command_rejected":
          setCommandResult({ answer: String(e.detail ?? e.answer ?? "Command could not be processed.") });
          break;
        default:
          break;
      }
    },
    [refreshAll, refreshIncidents, refreshMetrics]
  );

  const socket = useChronoSocket(onEvent);
  const displayedState = viewMode === "before" ? beforeState ?? socket.state
    : viewMode === "whatif" ? whatIfState ?? socket.state : socket.state;
  // Equal full-state WS frames must not cause duplicate HTTP requests. Including
  // the request key on results also prevents stale paths flashing after a change.
  const snapshotKey = displayedState ? JSON.stringify(displayedState) : "";
  const routeKey = routeConfig && snapshotKey ? JSON.stringify({ ...routeConfig, state: displayedState }) : "";
  const routeResult = routeResponse?.key === routeKey ? routeResponse.result : null;
  const power = powerResponse?.key === snapshotKey ? powerResponse.result : null;

  useEffect(() => {
    if (!graph) return;
    const origin = graph.nodes.find((node) => node.kind === "depot")?.id;
    const destination = graph.hospitals[0]?.node_id;
    setRouteConfig(origin && destination ? { vehicle_type: "ambulance", origin, destination_node: destination } : null);
    setSelectedItems([]);
    setSelection(null);
    setWhatIfState(null);
  }, [graph]);

  useEffect(() => {
    if (!routeKey) return;
    let active = true;
    void api.vehicleRoute(JSON.parse(routeKey)).then((result) => {
      if (active) setRouteResponse({ key: routeKey, result });
    }).catch((error: unknown) => {
      if (active) setRouteResponse({ key: routeKey, result: { answer: String(error) } });
    });
    return () => { active = false; };
  }, [routeKey]);

  useEffect(() => {
    if (!snapshotKey) return;
    let active = true;
    void api.previewPower(JSON.parse(snapshotKey)).then((result) => {
      if (active) setPowerResponse({ key: snapshotKey, result });
    }).catch(() => { if (active) setPowerResponse(null); });
    return () => { active = false; };
  }, [snapshotKey]);

  useEffect(() => {
    api
      .city()
      .then(setGraph)
      .catch(() => undefined);
    refreshAll();
  }, [refreshAll]);

  const selectEntity = useCallback(async (next: MapSelection | null, additive = false) => {
    setSelection(next);
    setSelectedItems((current) => !next ? [] : !additive ? [next]
      : current.some((item) => item.id === next.id) ? current.filter((item) => item.id !== next.id) : [...current, next]);
    setSelectedHospital(null);
    setDiagnostics(null);
    if (!next) return;
    if (next.type === "hospital") {
      try {
        setSelectedHospital(await api.hospital(next.id));
      } catch {
        /* hospital details are optional for imported maps */
      }
    } else if (["pipeline", "waterway", "water_works", "wastewater_plant"].includes(next.type)) {
      try {
        setDiagnostics(await api.diagnostics("water"));
      } catch {
        /* backend offline */
      }
    }
  }, []);

  const previewSelection = () => {
    if (!selection) return;
    if (selection.type === "edge" || selection.type === "underpass") quickCommand("close the selected road");
    else if (selection.type === "substation") quickCommand("disable selected feature");
    else if (selection.type === "power_line") quickCommand("break the selected power line");
    else if (["pipeline", "waterway", "water_works", "wastewater_plant"].includes(selection.type)) quickCommand("break the selected water pipe");
  };

  const runCommand = async (overrideText?: string) => {
    const text = (overrideText ?? commandText).trim();
    if (!text || commandBusy) return;
    if (overrideText) setCommandText(overrideText);
    setCommandBusy(true);
    try {
      const result = await api.runCommand({
        text,
        start_from: "current",
        selected_entity_id: selection?.id,
        selected_entity_ids: selection ? [selection.id] : [],
        selected_entity_type: selection?.type,
        base_state: displayedState,
      });
      setCommandResult(result);
      const after = result.after_state as CitySnapshot | undefined;
      if (after) {
        setWhatIfState(after);
        setViewMode("whatif");
      }
    } catch (error) {
      setCommandResult({ answer: error instanceof Error ? error.message : "Command failed." });
    } finally {
      setCommandBusy(false);
    }
  };

  const quickCommand = (text: string) => { void runCommand(text); };

  const calculateRoute = (vehicleType: RouteRequest["vehicle_type"]) => {
    const origin = routeConfig?.origin ?? graph?.nodes.find((node) => node.kind === "depot")?.id;
    const destination = selection?.type === "hospital"
      ? graph?.hospitals.find((hospital) => hospital.id === selection.id)?.node_id
      : vehicleType === "ambulance" ? graph?.hospitals[0]?.node_id
      : graph?.edges.find((edge) => edge.id === selection?.id)?.src ?? selection?.id;
    if (origin && destination) setRouteConfig({ vehicle_type: vehicleType, origin, destination_node: destination });
  };

  const previewHazards = async (hazards: Array<Record<string, unknown>>) => {
    if (commandBusy) return;
    setCommandBusy(true);
    try {
      const result = await api.runSimulation({ start_from: "current", base_state: displayedState, hazards });
      setWhatIfState(result.after_state as CitySnapshot);
      setViewMode("whatif");
      setCommandResult(result);
    } catch (error) {
      setCommandResult({ answer: error instanceof Error ? error.message : "Simulation failed" });
      throw error;
    } finally {
      setCommandBusy(false);
    }
  };

  const submitComplaint = async (body: { zone: string; category: "flood" | "blackout" | "pipe_leak" | "traffic"; text: string; count: number; state?: CitySnapshot | null; target_id?: string; target_type?: "road" | "residential_building" }): Promise<Record<string, unknown>> => {
    const payload = { ...body };
    if (payload.state == null) delete payload.state;
    if (!payload.target_id || !payload.target_type) {
      delete payload.target_id;
      delete payload.target_type;
    }
    const result = await api.submitComplaint(payload);
    setCommunity(await api.communityState());
    setCommandResult(result);
    return result;
  };

  const previewPipeline = async (assetId: string, pressure: number) => {
    if (!Number.isFinite(pressure) || pressure < 0 || pressure > 1000) throw new Error("Pressure must be between 0 and 1000 kPa.");
    const result = await api.pipelinePreview({ asset_id: assetId, pressure_kpa: pressure, base_state: displayedState });
    setWhatIfState(result.after_state as CitySnapshot);
    setViewMode("whatif");
    setCommandResult(result);
  };

  // ---- controls ----
  const start = async (mode: "combined" | "flood" | "trip") => {
    setRunning(true);
    setRunStartedAt(Date.now());
    setVerifiedAt(null);
    setCriticIterations(0);
    setBeforeState(null);
    setWhatIfState(null);
    setViewMode("present");
    try {
      await api.startScenario(mode); // resolves when the pipeline has verified a plan
      setVerifiedAt((v) => v ?? Date.now());
    } catch {
      /* backend offline */
    } finally {
      setRunning(false);
      refreshAll();
    }
  };

  const reset = async () => {
    try {
      await api.reset();
    } catch {
      /* backend offline */
    }
    setRunning(false);
    setBeforeState(null);
    setWhatIfState(null);
    setPlan(null);
    setViewMode("present");
    refreshAll();
  };

  const whatIf = async () => {
    try {
      const branch = await api.whatIf(
        [
          {
            tool: "traffic.clear_flood",
            entity_ids: ["E_J4_J6_U1"],
            params: { edge_id: "E_J4_J6_U1" },
            impact: "MEDIUM",
            rationale: "what-if: clear the underpass flood",
            owner: "what-if",
          },
          {
            tool: "power.restore_substation",
            entity_ids: ["S2"],
            params: { substation_id: "S2" },
            impact: "HIGH",
            rationale: "what-if: restore tripped substation S2",
            owner: "what-if",
          },
        ],
        "clear flood + restore S2"
      );
      if (branch.after_state) {
        setWhatIfState(branch.after_state);
        setViewMode("whatif");
      }
    } catch {
      /* backend offline */
    }
  };

  return (
    <div className="app">
      <header className="app-head">
        <h1>
          ChronoTwin<span className="accent">.</span>
        </h1>
        <span className="subtitle">Multi-agent operating layer for a city digital twin</span>
        <span className={`conn ${socket.connected ? "on" : "off"}`}>
          {socket.connected ? "LIVE" : "OFFLINE"}
        </span>
        <button className={`btn btn-toggle ${surface === "city" ? "active" : ""}`} onClick={() => setSurface("city")}>City Simulation</button>
        <button className={`btn btn-toggle ${surface === "operator" ? "active" : ""}`} onClick={() => setSurface("operator")}>Operator Dashboard</button>
      </header>

      {surface === "city" && <div className="layer-toolbar">
        <span className="muted">Layers</span>
        {(Object.keys(layers) as Array<keyof typeof layers>).map((layer) => (
          <button key={layer} className={`btn btn-toggle ${layers[layer] ? "active" : ""}`} onClick={() => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}>
            {layer[0].toUpperCase() + layer.slice(1)}
          </button>
        ))}
      </div>}
      {surface === "operator" ? <OperatorDashboard onRefresh={refreshAll} /> : <main className="app-main">
        <div className="col col-left">
          <IncidentPanel incidents={incidents} cascade={cascade} />
          <ChatterPanel
            events={socket.events}
            state={socket.state}
            plan={plan}
            selection={selection}
            commandText={commandText}
            commandBusy={commandBusy}
            setCommandText={setCommandText}
            onCommand={(text) => void runCommand(text)}
            onOpenOperator={() => setSurface("operator")}
          />
        </div>
        <div className="col col-center">
          <TwinScene
            graph={graph}
            state={socket.state}
            beforeState={beforeState}
            whatIfState={whatIfState}
            cascade={cascade}
            viewMode={viewMode}
            onSelect={selectEntity}
            selection={selection}
            selectedId={selection?.id}
            routeResult={routeResult}
            powerDiagnostics={power}
            busy={commandBusy}
            onPreview={previewHazards}
            onPipelinePreview={previewPipeline}
            onPreviewSelection={previewSelection}
            selectedIds={selectedItems.map((item) => item.id)}
            outageNodeIds={power?.affected_nodes ?? []}
            layers={layers}
          />
        </div>
        <div className="col col-right">
          <SimulationPanel graph={graph} selectedItems={selectedItems} onSelectionChange={setSelectedItems}
            busy={commandBusy} onPreview={previewHazards} power={power} routeConfig={routeConfig}
            onRouteChange={setRouteConfig} routeResult={routeResult} viewMode={viewMode}
            onClearPreview={() => { setWhatIfState(null); setViewMode("present"); }} />
          <ComplaintsPanel graph={graph} selection={selection} state={viewMode === "present" ? null : displayedState} community={community} busy={commandBusy} onSubmit={submitComplaint} />
          <ControlPanel
            graph={graph}
            selection={selection}
            hospital={selectedHospital}
            diagnostics={selection?.type === "substation" && power ? { ...power } : diagnostics}
            routeResult={routeResult}
            onQuickCommand={quickCommand}
            onPreviewSelection={previewSelection}
             onRoute={calculateRoute}
          />
          <button className="btn btn-primary" onClick={() => setSurface("operator")}>Review plans &amp; audit history in Operator Dashboard</button>
        </div>
      </main>}

      <TimelineBar
        onStart={start}
        onReset={reset}
        onWhatIf={whatIf}
        running={running}
        runStartedAt={runStartedAt}
        verifiedAt={verifiedAt}
        viewMode={viewMode}
        setViewMode={setViewMode}
        metrics={metrics}
        compare={compare}
        criticIterations={criticIterations}
      />
    </div>
  );
}
