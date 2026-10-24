import { useEffect, useState } from "react";
import type { ActionLogEntry, Action, Impact, JointPlan } from "../types";
import { api } from "../api";

interface Props {
  plan: JointPlan | null;
  onAction: () => void;
}

const impactClass: Record<Impact, string> = {
  HIGH: "imp imp-high",
  MEDIUM: "imp imp-med",
  LOW: "imp imp-low",
};

function actionText(action: Action): string {
  const id = action.entity_ids[0] ?? "the affected area";
  switch (action.tool) {
    case "traffic.close_edge": return `Close road ${id}`;
    case "traffic.flood_edge": return `Mark road ${id} as flooded`;
    case "traffic.reroute": return `Redirect traffic away from ${action.params.slow_edge_id ?? id}`;
    case "traffic.signal_dark": return `Account for failed traffic signals`;
    case "power.trip_substation": return `Take power station ${action.params.substation_id ?? id} offline`;
    case "power.restore_substation": return `Restore power station ${action.params.substation_id ?? id}`;
    case "power.reroute_feeder": return `Restore power by rerouting ${action.params.from_feeder ?? "the feeder"}`;
    case "power.load_shed": return `Reduce load on non-critical power feeders`;
    case "power.set_load": return `Set power station ${action.params.substation_id ?? id} load to ${action.params.load_mw ?? "the requested level"} MW`;
    case "power.break_line": return `Mark power line ${id} as failed`;
    case "water.break_pipe": return `Mark water asset ${id} as broken`;
    case "water.set_pressure": return `Adjust water pressure for ${id}`;
    case "emergency.dispatch": return `Dispatch an ambulance to the hospital`;
    default: return action.rationale || action.tool.split(".").join(" ");
  }
}

function statusText(status: string): string {
  switch (status) {
    case "PENDING_APPROVAL": return "Waiting for your approval";
    case "VERIFIED": return "Checked and ready";
    case "APPROVED": return "Approved — ready to execute";
    case "EXECUTED": return "Applied to the city twin";
    case "FAILED": return "Rejected or failed";
    default: return "Being prepared";
  }
}

function verdictMetrics(plan: JointPlan): string | null {
  const m = plan.metrics ?? {};
  const keys = Object.keys(m);
  if (keys.length === 0) return null;
  return keys.map((k) => `${k.split("_").join(" ")} ${Number(m[k]).toFixed(2)}`).join(" · ");
}

export default function PlanPanel({ plan, onAction }: Props) {
  const [log, setLog] = useState<ActionLogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refreshLog = async () => {
    try {
      const entries = await api.actionLog();
      setLog(entries.slice(-8).reverse());
    } catch {
      /* backend offline */
    }
  };

  useEffect(() => { void refreshLog(); }, [plan?.id, plan?.status]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      const out = (await fn()) as { ok?: boolean; error?: string };
      const error = out?.error;
      setMessage(out?.ok === false ? `Request failed: ${error ?? "unknown error"}` : "Request accepted.");
      onAction();
      await refreshLog();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  };

  const approve = () => plan && act(() => api.approve(plan.id, true));
  const reject = () => plan && act(() => api.approve(plan.id, false));
  const execute = () => plan && act(() => api.execute(plan.id));
  const removeAction = (actionId: string) => plan && act(() => api.editPlan(plan.id, [actionId]));

  return (
    <section className="panel plan-panel">
      <header className="panel-head">
        <span>What the system plans to do</span>
        {plan && <span className={`badge ${plan.status === "PENDING_APPROVAL" ? "badge-warn" : plan.status === "FAILED" ? "badge-critical" : "badge-ok"}`}>{statusText(plan.status)}</span>}
      </header>
      <div className="panel-body">
        {!plan ? <p className="muted">Run a scenario or ask the assistant for a simulation. Any proposed response will appear here in plain language.</p> : (
          <>
            <p className="plan-summary">The system reviewed the active incidents and prepared this response:</p>
            <div className="plan-actions-readable">
              {plan.actions.length === 0 && <p className="muted">No changes are currently proposed.</p>}
              {plan.actions.map((action) => (
                <div key={action.id} className="readable-action">
                  <span className={impactClass[action.impact]}>{action.impact}</span>
                  <span>{actionText(action)}</span>
                  {(plan.status === "PENDING_APPROVAL" || plan.status === "VERIFIED" || plan.status === "REVISED") && <button className="btn btn-small" disabled={busy} onClick={() => removeAction(action.id)}>Remove</button>}
                </div>
              ))}
            </div>

            {plan.resolution && <div className="plan-note"><strong>Coordination note</strong><div className="muted">{plan.resolution}</div></div>}
            {plan.critic_feedback && <div className="plan-note"><strong>Safety check</strong><div className="muted">{plan.critic_feedback}</div></div>}
            {verdictMetrics(plan) && <div className="muted plan-metrics">{verdictMetrics(plan)}</div>}

            <div className="btn-row">
              {plan.status === "PENDING_APPROVAL" && <>
                <button className="btn btn-primary" disabled={busy} onClick={approve}>Approve response</button>
                <button className="btn btn-danger" disabled={busy} onClick={reject}>Reject</button>
              </>}
              {plan.status === "APPROVED" && <button className="btn btn-primary" disabled={busy} onClick={execute}>Apply response</button>}
              {plan.status === "EXECUTED" && <span className="badge badge-ok">Response applied</span>}
              {plan.status === "VERIFIED" && <span className="muted">No high-impact approval is needed.</span>}
              {plan.status === "FAILED" && <span className="muted">No action was applied.</span>}
            </div>
            {message && <p className="muted approval-message">{message}</p>}

            <details className="plan-details">
              <summary className="muted">Show technical details</summary>
              <div className="chips"><span className="chip">plan version {plan.version}</span><span className="chip">{plan.proposals.length} specialist inputs</span><span className="chip">{plan.conflicts.length} coordination conflicts</span></div>
              {log.length > 0 && <div className="action-log">
                {log.map((entry) => <div key={entry.id} className="log-line"><span className="chip">{entry.phase}</span><code>{entry.tool}</code><span className="muted">{entry.ok ? "ok" : "failed"}</span></div>)}
              </div>}
            </details>
          </>
        )}
      </div>
    </section>
  );
}
