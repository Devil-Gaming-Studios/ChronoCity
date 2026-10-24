import type { Cascade, Incident } from "../types";

interface Props {
  incidents: Incident[];
  cascade: Cascade | null;
}

const sevClass: Record<string, string> = {
  CRITICAL: "sev sev-critical",
  WARNING: "sev sev-warning",
  INFO: "sev sev-info",
};

export default function IncidentPanel({ incidents, cascade }: Props) {
  const open = incidents.filter((i) => !i.resolved);
  const closed = incidents.filter((i) => i.resolved);

  return (
    <section className="panel">
      <header className="panel-head">
        <span>Incidents</span>
        <span className={`badge ${open.length ? "badge-critical" : "badge-ok"}`}>
          {open.length} open
        </span>
      </header>

      <div className="panel-body">
        {open.length === 0 && <p className="muted">No active incidents.</p>}
        {open.map((i) => (
          <div key={i.id} className={`incident ${i.severity}`}>
            <div className="incident-row">
              <span className={sevClass[i.severity]}>{i.severity}</span>
              <span className="incident-title">{i.title || i.kind}</span>
              <span className="muted">P{i.priority}</span>
            </div>
            {i.detail && <p className="incident-detail">{i.detail}</p>}
            <div className="chips">
              <span className="chip">{i.zone}</span>
              {i.entity_ids.map((e) => (
                <span key={e} className="chip chip-entity">
                  {e}
                </span>
              ))}
              <span className="chip chip-trust">trust {(i.trust ?? 1).toFixed(2)}</span>
            </div>
          </div>
        ))}

        {closed.length > 0 && (
          <details className="resolved-group">
            <summary className="muted">Resolved ({closed.length})</summary>
            {closed.map((i) => (
              <div key={i.id} className="incident resolved">
                <span className="incident-title">{i.title || i.kind}</span>
              </div>
            ))}
          </details>
        )}

        {cascade && (
          <div className="cascade">
            <div className="incident-row">
              <span className="sev sev-critical">CASCADE</span>
              <span className="incident-title">
                {cascade.contained_hops} hop{cascade.contained_hops === 1 ? "" : "s"} from root failure
              </span>
            </div>
            <div className="chips">
              {cascade.roots.map((r) => (
                <span key={r} className="chip chip-entity chip-root">
                  {r} (root)
                </span>
              ))}
              {cascade.affected
                .filter((a) => !cascade.roots.includes(a))
                .map((a) => (
                  <span key={a} className="chip chip-affected">
                    {a}
                  </span>
                ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
