import { useEffect, useState } from "react";
import type { ActionLogEntry, Action, Impact, JointPlan } from "../types";
import { api } from "../api";

interface Props {
  plan: JointPlan | null;
  onAction: () => void; // refresh after approve/reject/execute
}

const impactClass: Record<Impact, string> = {
  HIGH: "imp imp-high",
  MEDIUM: "imp imp-med",
  LOW: "imp imp-low",
};

function verdictMetrics(plan: JointPlan): string | null {
  const m = plan.metrics ?? {};
  const keys = Object.keys(m);
  if (keys.length === 0) return null;
  return keys.map((k) => `${k.split("_").join(" ")} ${Number(m[k]).toFixed(2)}`).join(" · ");
}

export default function PlanPanel({ plan, onAction }: Props) {
  const [log, setLog] = useState<ActionLogEntry[]>([]);
  const [busy, setBusy] = useState(false);

  const refreshLog = async () => {
    try {
      const entries = await api.actionLog();
      setLog(entries.slice(-8).reverse());
    } catch {
      /* backend offline */
    }
  };

  useEffect(() => {
    void refreshLog();
  }, [plan?.id, plan?.status]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      const out = (await fn()) as { ok?: boolean; error?: string };
      const error = out?.error;
      if (out?.ok === false && error) {
        setLog((prev) => [
          {
            id: `err${Date.now()}`,
            plan_id: plan?.id ?? "",
            action_id: "",
            tool: "api",
            phase: "approve",
            actor: "ui",
            impact: "LOW",
            ok: false,
            detail: error,
            ts: Date.now() / 1000,
          },
          ...prev,
        ]);
      }
      onAction();
      await refreshLog();
    } finally {
      setBusy(false);
    }
  };

  const approve = () => plan && act(() => api.approve(plan.id, true));
  const reject = () => plan && act(() => api.approve(plan.id, false));
  const execute = () => plan && act(() => api.execute(plan.id));

  if (!plan) {
    return (
      <section className="panel">
        <header className="panel-head">
          <span>Joint Plan</span>
        </header>
        <div className="panel-body">
          <p className="muted">No plan yet. Trigger a scenario to watch the agents work.</p>
        </div>
      </section>
    );
  }

  const statusClass =
    plan.status === "EXECUTED" || plan.status === "VERIFIED"
      ? "badge-ok"
      : plan.status === "PENDING_APPROVAL"
        ? "badge-warn"
        : plan.status === "FAILED"
          ? "badge-critical"
          : "";
  const metricsLine = verdictMetrics(plan);

  return (
    <section className="panel">
      <header className="panel-head">
        <span>Joint Plan v{plan.version}</span>
        <span className={`badge ${statusClass}`}>{plan.status}</span>
      </header>
      <div className="panel-body">
        <p className="plan-summary">{plan.resolution || "Negotiating…"}</p>

        {plan.conflicts.length > 0 && (
          <div className="conflicts">
            <h4>Conflicts ({plan.conflicts.length})</h4>
            {plan.conflicts.map((c) => (
              <p key={c.id} className="conflict">
                <span className={`chip chip-${c.kind}`}>{c.kind}</span> {c.description}
              </p>
            ))}
          </div>
        )}

        {plan.proposals.map((p, i) => (
          <div key={p.id ?? `${p.agent}-${i}`} className="proposal">
            <div className="incident-row">
              <span className="proposal-agent">{p.agent}</span>
              <span className={`chip chip-${p.domain}`}>{p.domain}</span>
            </div>
            <p className="muted">{p.summary}</p>
            <div className="chips">
              <span className="chip">reads: {p.read_calls.length}</span>
              <span className="chip">
                actions: {Array.isArray(p.actions) ? p.actions.length : p.actions}
              </span>
            </div>
          </div>
        ))}

        <h4>Actions ({plan.actions.length})</h4>
        {plan.actions.length === 0 && <p className="muted">All actions dropped in negotiation.</p>}
        {plan.actions.map((a: Action) => (
          <div key={a.id} className="action-row">
            <span className={impactClass[a.impact]}>{a.impact}</span>
            <code>{a.tool}</code>
            <span className="muted">{a.owner}</span>
          </div>
        ))}

        <div className={`verdict ${plan.status === "FAILED" ? "fail" : "pass"}`}>
          <div className="incident-row">
            <span>Critic simulation</span>
          </div>
          {metricsLine && <p className="muted">{metricsLine}</p>}
          {plan.critic_feedback && <p className="verdict-note">{plan.critic_feedback}</p>}
        </div>

        <div className="btn-row">
          {plan.status === "PENDING_APPROVAL" && (
            <>
              <button className="btn btn-primary" disabled={busy} onClick={approve}>
                Approve
              </button>
              <button className="btn btn-danger" disabled={busy} onClick={reject}>
                Reject
              </button>
            </>
          )}
          {plan.status === "APPROVED" && (
            <button className="btn btn-primary" disabled={busy} onClick={execute}>
              Execute
            </button>
          )}
          {plan.status === "EXECUTED" && <span className="badge badge-ok">Executed on twin</span>}
          {plan.status === "VERIFIED" && (
            <span className="muted">Verified — no HIGH actions, safe to execute</span>
          )}
          {["DRAFT", "SUBMITTED", "REVISED"].includes(plan.status) && (
            <span className="muted">Waiting for verification…</span>
          )}
          {plan.status === "FAILED" && <span className="muted">Rejected by operator</span>}
        </div>

        {log.length > 0 && (
          <details className="action-log" open>
            <summary className="muted">Action log</summary>
            {log.map((e) => (
              <div key={e.id} className="log-line">
                <span className="chip">{e.phase}</span>
                <code>{e.tool}</code>
                <span className="muted">
                  {e.ok ? "ok" : "fail"} · {e.actor}
                </span>
              </div>
            ))}
          </details>
        )}
      </div>
    </section>
  );
}
