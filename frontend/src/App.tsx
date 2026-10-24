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
} from "./types";
import TwinScene, { type ViewMode } from "./components/TwinScene";
import IncidentPanel from "./components/IncidentPanel";
import PlanPanel from "./components/PlanPanel";
import ChatterPanel from "./components/ChatterPanel";
import TimelineBar from "./components/TimelineBar";

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
        case "executed":
        case "incident":
          refreshIncidents();
          refreshMetrics();
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

      <main className="app-main">
        <div className="col col-left">
          <IncidentPanel incidents={incidents} cascade={cascade} />
          <ChatterPanel events={socket.events} state={socket.state} />
        </div>
        <div className="col col-center">
          <TwinScene
            graph={graph}
            state={socket.state}
            beforeState={beforeState}
            whatIfState={whatIfState}
            cascade={cascade}
            viewMode={viewMode}
          />
        </div>
        <div className="col col-right">
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
