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
} from "./types";
import TwinScene, { type ViewMode } from "./components/TwinScene";
import IncidentPanel from "./components/IncidentPanel";
import PlanPanel from "./components/PlanPanel";
import ChatterPanel from "./components/ChatterPanel";
import TimelineBar from "./components/TimelineBar";
import ControlPanel from "./components/ControlPanel";

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
  const [routeResult, setRouteResult] = useState<Record<string, unknown> | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [layers, setLayers] = useState({ power: true, traffic: true, emergency: true, reports: true });

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
        case "incident":
          refreshIncidents();
          refreshMetrics();
          break;
        case "approval":
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

  useEffect(() => {
    api
      .city()
      .then(setGraph)
      .catch(() => undefined);
    refreshAll();
  }, [refreshAll]);

  const selectEntity = useCallback(async (next: MapSelection | null) => {
    setSelection(next);
    setSelectedHospital(null);
    setDiagnostics(null);
    setRouteResult(null);
    if (!next) return;
    if (next.type === "hospital") {
      try {
        setSelectedHospital(await api.hospital(next.id));
      } catch {
        /* hospital details are optional for imported maps */
      }
    } else if (next.type === "substation") {
      try {
        setDiagnostics(await api.diagnostics("power"));
      } catch {
        /* backend offline */
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
    if (!text) return;
    if (overrideText) setCommandText(overrideText);
    setCommandBusy(true);
    try {
      const result = await api.runCommand({
        text,
        start_from: "current",
        selected_entity_id: selection?.id,
        selected_entity_type: selection?.type,
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

  const respondToApproval = async (approved: boolean) => {
    if (!plan) return;
    setApprovalBusy(true);
    try {
      const result = await api.approve(plan.id, approved, approved ? "Approved from agent chat" : "Rejected from agent chat");
      if (result?.ok === false) {
        throw new Error(String(result.error ?? "Approval request failed."));
      }
      await refreshPlan();
      setCommandResult({ answer: approved ? "Plan approved. Execute it from the plan panel when ready." : "Plan rejected. No actions were executed." });
    } catch (error) {
      setCommandResult({ answer: error instanceof Error ? error.message : "Approval request failed." });
    } finally {
      setApprovalBusy(false);
    }
  };

  const routeVehicle = async (vehicleType: "firetruck" | "police" | "ambulance") => {
    if (!selection) return;
    const body: { vehicle_type: typeof vehicleType; hospital_id?: string; destination_node?: string; incident_edge_id?: string } = { vehicle_type: vehicleType };
    if (selection.type === "hospital") body.hospital_id = selection.id;
    else if (selection.type === "edge") {
      const edge = graph?.edges.find((item) => item.id === selection.id);
      body.destination_node = edge?.src;
      body.incident_edge_id = selection.id;
    } else body.destination_node = selection.id;
    try {
      setRouteResult(await api.vehicleRoute(body));
    } catch (error) {
      setRouteResult({ answer: error instanceof Error ? error.message : "Route calculation failed" });
    }
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
      </header>

      <div className="layer-toolbar">
        <span className="muted">Layers</span>
        {(Object.keys(layers) as Array<keyof typeof layers>).map((layer) => (
          <button key={layer} className={`btn btn-toggle ${layers[layer] ? "active" : ""}`} onClick={() => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}>
            {layer[0].toUpperCase() + layer.slice(1)}
          </button>
        ))}
      </div>
      <main className="app-main">
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
            approvalBusy={approvalBusy}
            onApprove={() => void respondToApproval(true)}
            onReject={() => void respondToApproval(false)}
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
            selectedId={selection?.id}
            layers={layers}
          />
        </div>
        <div className="col col-right">
          <ControlPanel
            graph={graph}
            selection={selection}
            hospital={selectedHospital}
            diagnostics={diagnostics}
            routeResult={routeResult}
            onQuickCommand={quickCommand}
            onPreviewSelection={previewSelection}
            onRoute={routeVehicle}
          />
          <PlanPanel plan={plan} onAction={refreshAll} />
        </div>
      </main>

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
