import { useEffect, useState } from "react";
import type { Compare, Metrics } from "../types";
import type { ViewMode } from "./TwinScene";

interface Props {
  onStart: (mode: "combined" | "flood" | "trip") => void;
  onReset: () => void;
  onWhatIf: () => void;
  running: boolean;
  runStartedAt: number | null;
  verifiedAt: number | null;
  viewMode: ViewMode;
  setViewMode: (m: ViewMode) => void;
  metrics: Metrics | null;
  compare: Compare | null;
  criticIterations: number;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

const fmtEta = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v)}s`);

export default function TimelineBar({
  onStart,
  onReset,
  onWhatIf,
  running,
  runStartedAt,
  verifiedAt,
  viewMode,
  setViewMode,
  metrics,
  compare,
  criticIterations,
}: Props) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);

  const verifiedSecs =
    runStartedAt != null && verifiedAt != null ? (verifiedAt - runStartedAt) / 1000 : null;
  const liveSecs = runStartedAt != null && verifiedAt == null ? (now - runStartedAt) / 1000 : null;

  const llmCalls = metrics?.llm_calls ?? null;
  const readings = metrics?.readings_processed ?? null;

  return (
    <footer className="timeline-bar">
      <div className="tb-group">
        <button className="btn" disabled={running} onClick={() => onStart("combined")}>
          Combined
        </button>
        <button className="btn" disabled={running} onClick={() => onStart("flood")}>
          Flood
        </button>
        <button className="btn" disabled={running} onClick={() => onStart("trip")}>
          Trip
        </button>
        <button className="btn btn-danger" onClick={onReset}>
          Reset
        </button>
        <button className="btn btn-warn" disabled={running} onClick={onWhatIf}>
          What-if ↯
        </button>
      </div>

      <div className="tb-group tb-view">
        {(["before", "present", "whatif"] as ViewMode[]).map((m) => (
          <button
            key={m}
            className={`btn btn-toggle ${viewMode === m ? "active" : ""}`}
            onClick={() => setViewMode(m)}
          >
            {m === "before" ? "Before" : m === "present" ? "Present" : "What-if"}
          </button>
        ))}
      </div>

      <div className="tb-group tb-stats">
        <Stat
          label="time to verified plan"
          value={
            verifiedSecs != null
              ? `${verifiedSecs.toFixed(2)}s`
              : liveSecs != null
                ? `${liveSecs.toFixed(1)}s…`
                : "—"
          }
        />
        <Stat label="ambulance ETA now" value={fmtEta(compare?.ambulance_eta_now_s)} />
        <Stat label="ETA baseline" value={fmtEta(compare?.ambulance_eta_baseline_s)} />
        <Stat label="dark signals" value={compare ? `${compare.dark_signals_now}` : "—"} />
        <Stat label="critic iters" value={`${criticIterations}`} />
        <Stat
          label="LLM calls / readings"
          value={llmCalls != null && readings ? `${llmCalls}/${readings}` : "—"}
        />
        <Stat
          label="mode"
          value={metrics?.llm_mode ?? "—"}
        />
      </div>
    </footer>
  );
}
