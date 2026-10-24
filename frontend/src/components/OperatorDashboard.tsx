import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuditEvent, AuditPage, CommunityState, JointPlan, SavedPlans } from "../types";
import PlanPanel from "./PlanPanel";

interface Props {
  onRefresh: () => void;
}

export default function OperatorDashboard({ onRefresh }: Props) {
  const [page, setPage] = useState<AuditPage | null>(null);
  const [saved, setSaved] = useState<SavedPlans | null>(null);
  const [pending, setPending] = useState<Array<{ plan: JointPlan; stale: boolean }>>([]);
  const [community, setCommunity] = useState<CommunityState | null>(null);
  const [before, setBefore] = useState<number | undefined>();
  const [kind, setKind] = useState("");
  const [scope, setScope] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Fetch the database, not the bounded socket transcript. Polling also catches
  // events produced while the City view or another client is open.
  useEffect(() => {
    let active = true;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const [events, plans, queue, complaints] = await Promise.all([
          api.auditEvents({ before, kind, scope, plan_id: planFilter }), api.auditPlans(offset),
          api.pendingPlans(), api.communityState(),
        ]);
        if (active) {
          setPage(events); setSaved(plans); setPending(queue.items); setCommunity(complaints); setError("");
        }
      } catch (cause) {
        if (active) setError(`History refresh failed. Displayed data may be stale. ${String(cause)}`);
      } finally { loading = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [before, kind, scope, planFilter, offset, revision]);

  const refresh = () => { setRevision((value) => value + 1); onRefresh(); };
  const eligible = community?.incidents.filter((item) => item.eligible_for_plan).map((item) => String(item.id)) ?? [];
  const generate = async (complaints: boolean) => {
    setBusy(true); setMessage("");
    try {
      const result = complaints ? await api.planCommunity(eligible) : await api.generatePlan();
      if (result.ok === false) throw new Error(String(result.error));
      setMessage("Response simulated. Review its safety verdict and actions below before approving.");
      refresh();
    } catch (cause) { setMessage(String(cause)); }
    finally { setBusy(false); }
  };
  const exportHistory = async () => {
    setExporting(true);
    try {
      const events: AuditEvent[] = [];
      let cursor: number | undefined;
      do {
        const batch = await api.auditEvents({ before: cursor, kind, scope, plan_id: planFilter, limit: 200 });
        events.push(...batch.items);
        cursor = batch.next_before ?? undefined;
      } while (cursor);
      const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(),
        filters: { kind, scope, plan_id: planFilter }, events }, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = "chronotwin-audit.json"; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setMessage(`Export failed: ${String(cause)}`); }
    finally { setExporting(false); }
  };

  return <main className="operator-dashboard">
    <section className="panel operator-overview">
      <header className="panel-head"><span>Operator control room</span><span>Persistent database history</span></header>
      <div className="panel-body">
        <p>City changes, What-if previews, agent work, safety verdicts and human decisions are recorded here. History survives restarts; old-runtime plans are read-only.</p>
        <div className="dashboard-grid">
          <div className="dashboard-card"><strong>{page?.total ?? "—"}</strong><span>matching audit records</span></div>
          <div className="dashboard-card"><strong>{pending.length}</strong><span>responses awaiting operator action</span></div>
          <div className="dashboard-card"><strong>{saved?.total ?? "—"}</strong><span>stored plans</span></div>
          <div className="dashboard-card"><strong>{page?.storage ?? "Connecting…"}</strong><span>durable local storage · refresh every 3s</span></div>
        </div>
        <p className="muted">Recording starts with this update. Previously lost in-memory events cannot be reconstructed. This is a local simulator, not a connection to real utility switches.</p>
        {error && <p role="alert" className="badge-critical">{error}</p>}
      </div>
    </section>

    <section className="operator-approvals" aria-label="Human approval queue">
      <h2>Human review &amp; intervention</h2>
      <p>Review the proposed targets, impacts and safety checks. Approve or reject with a note; applying an approved response is a separate action.</p>
      <div className="btn-row">
        <button className="btn btn-primary" disabled={busy} onClick={() => void generate(false)}>{busy ? "Planning…" : "Plan verified live incidents"}</button>
        <button className="btn" disabled={busy || !eligible.length} onClick={() => void generate(true)}>Plan verified live complaints</button>
        <button className="btn" onClick={refresh}>Refresh dashboard</button>
      </div>
      <p className="muted">What-if complaints are recorded but cannot authorize live actions. Use a live scenario to exercise the approval workflow.</p>
      {message && <p role="status">{message}</p>}
      {!pending.length && <p className="audit-empty">No responses awaiting review. Rejected or completed responses remain in the stored history below.</p>}
      {pending.map(({ plan, stale }) => <div key={plan.id}>
        {stale && <p role="alert" className="badge-critical">Plan {plan.id} is stale because the city changed. Reject it or generate a fresh response; approval and execution are blocked.</p>}
        <PlanPanel plan={plan} onAction={refresh} stale={stale} />
      </div>)}
    </section>

    <section className="panel operator-history">
      <header className="panel-head"><span>Documented activity history</span><span>Newest first · local timestamps</span></header>
      <div className="panel-body">
        <div className="audit-filters">
          <label>Event type<select value={kind} onChange={(event) => { setKind(event.target.value); setBefore(undefined); }}>
            <option value="">All events</option>{page?.kinds.map((item) => <option key={item} value={item}>{item.split("_").join(" ")}</option>)}
          </select></label>
          <label>Scope<select value={scope} onChange={(event) => { setScope(event.target.value); setBefore(undefined); }}>
            <option value="">Live and What-if</option><option value="live">Live simulation</option><option value="preview">What-if only</option>
          </select></label>
          <label>Plan ID<input value={planFilter} onChange={(event) => { setPlanFilter(event.target.value); setBefore(undefined); }} placeholder="All plans" /></label>
          <button className="btn" disabled={exporting} onClick={() => void exportHistory()}>{exporting ? "Exporting…" : "Download matching history (.json)"}</button>
        </div>
        {page?.items.length === 0 && <p className="audit-empty">No records match these filters.</p>}
        <ol className="audit-timeline">
          {page?.items.map((event) => <li key={event.id}>
            <div className="audit-event-heading"><time dateTime={new Date(event.ts * 1000).toISOString()}>{new Date(event.ts * 1000).toLocaleString()}</time>
              <span className="chip">#{event.id} · {event.kind}</span><span className={event.scope === "preview" ? "badge badge-warn" : "badge badge-ok"}>{event.scope === "preview" ? "What-if · no live change" : "Live simulation"}</span></div>
            <strong>{event.summary}</strong>
            <p className="muted">{event.actor} · {event.city} {event.plan_id && `· Plan ${event.plan_id}`}</p>
            <details><summary>Recorded details / evidence</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>
          </li>)}
        </ol>
        <div className="btn-row"><button className="btn" disabled={!before} onClick={() => setBefore(undefined)}>Latest records</button>
          <button className="btn" disabled={!page?.next_before} onClick={() => setBefore(page?.next_before ?? undefined)}>Older records</button></div>
      </div>
    </section>

    <section className="panel operator-history">
      <header className="panel-head">Saved plan history · read-only records</header>
      <div className="panel-body">
        {!saved?.items.length && <p>No plans stored yet.</p>}
        {saved?.items.map((item) => <details className="saved-plan" key={`${item.runtime_id}:${item.plan.id}`}>
          <summary>{item.plan.id} · v{item.plan.version} · {item.plan.status} · {new Date(item.updated * 1000).toLocaleString()}</summary>
          <p>{item.plan.critic_feedback || item.plan.resolution}</p>
          <ul>{item.plan.actions.map((action) => <li key={action.id}><strong>{action.tool}</strong> · {action.entity_ids.join(", ")} · {action.impact} — {action.rationale}</li>)}</ul>
          <button className="btn" onClick={() => { setPlanFilter(item.plan.id); setBefore(undefined); }}>Show this plan’s audit trail</button>
          <pre>{JSON.stringify(item.plan, null, 2)}</pre>
        </details>)}
        <div className="btn-row"><button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Newer plans</button>
          <button className="btn" disabled={offset + 20 >= (saved?.total ?? 0)} onClick={() => setOffset(offset + 20)}>Older plans</button></div>
      </div>
    </section>
  </main>;
}
