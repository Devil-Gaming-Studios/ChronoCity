import type { CityGraph, HospitalInfo, MapSelection } from "../types";

interface Props {
  graph: CityGraph | null;
  selection: MapSelection | null;
  hospital: HospitalInfo | null;
  diagnostics: Record<string, unknown> | null;
  commandText: string;
  commandBusy: boolean;
  commandResult: Record<string, unknown> | null;
  routeResult: Record<string, unknown> | null;
  setCommandText: (value: string) => void;
  onCommand: () => void;
  onPreviewSelection: () => void;
  onRoute: (vehicleType: "firetruck" | "police" | "ambulance") => void;
}

export default function ControlPanel({
  graph,
  selection,
  hospital,
  diagnostics,
  commandText,
  commandBusy,
  commandResult,
  routeResult,
  setCommandText,
  onCommand,
  onPreviewSelection,
  onRoute,
}: Props) {
  const station = diagnostics?.probable_station as Record<string, unknown> | undefined;
  const answer = String(routeResult?.answer ?? commandResult?.answer ?? "");
  const explanation = Array.isArray(commandResult?.explanation) ? commandResult?.explanation as string[] : [];

  return (
    <section className="panel panel-controls">
      <header className="panel-head">
        <span>Interactive controls</span>
        <span className="muted">select · simulate · route</span>
      </header>
      <div className="panel-body">
        <div className="control-help muted">Click a road, hospital, station, pipe, or power line in the 3D map.</div>

        <div className="selection-card">
          <h4>Selected feature</h4>
          {selection ? (
            <>
              <div className="selected-title">{selection.label}</div>
              <div className="chips"><span className="chip chip-entity">{selection.type}</span><span className="chip">{selection.id}</span></div>
              {selection.type !== "building" && (
                <button className="btn btn-warn" onClick={onPreviewSelection}>
                  Preview disable in What-if
                </button>
              )}
              {(selection.type === "hospital" || selection.type === "edge" || selection.type === "substation") && (
                <div className="btn-row compact">
                  <button className="btn" onClick={() => onRoute("firetruck")}>Firetruck route</button>
                  <button className="btn" onClick={() => onRoute("police")}>Police route</button>
                  {selection.type === "hospital" && <button className="btn" onClick={() => onRoute("ambulance")}>Ambulance route</button>}
                </div>
              )}
            </>
          ) : <p className="muted">Nothing selected.</p>}
        </div>

        {hospital && (
          <div className="hospital-card">
            <h4>Hospital capacity</h4>
            <div className="selected-title">{hospital.name}</div>
            {hospital.departments.map((department) => (
              <div className="department-row" key={department.id}>
                <span>{department.name}</span>
                <span className={department.available_beds === 0 ? "badge badge-critical" : "badge badge-ok"}>
                  {department.available_beds}/{department.total_beds} beds
                </span>
              </div>
            ))}
          </div>
        )}

        {station && (
          <div className="diagnostic-card">
            <h4>Power diagnosis</h4>
            <div><span className="muted">Likely station:</span> {String(station.substation_id)}</div>
            <div><span className="muted">Status:</span> {String(station.status)}</div>
            <div><span className="muted">Cause:</span> {String(station.probable_cause)}</div>
          </div>
        )}

        <div className="command-card">
          <h4>Scenario command</h4>
          <div className="command-row">
            <input
              className="command-input"
              value={commandText}
              onChange={(event) => setCommandText(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") onCommand(); }}
              placeholder="e.g. rain 120 mm or set substation S2 load to 45 MW"
              disabled={commandBusy}
            />
            <button className="btn btn-primary" onClick={onCommand} disabled={commandBusy || !commandText.trim()}>
              {commandBusy ? "Running…" : "Run"}
            </button>
          </div>
          <p className="muted command-examples">Try: “break wire ASSET_ID”, “break pipe ASSET_ID”, “trip substation S2”, or “disable selected feature”.</p>
        </div>

        {answer && <div className="control-result"><strong>{answer}</strong>{explanation.map((line) => <div key={line} className="muted">{line}</div>)}</div>}
        {routeResult?.route != null && <div className="control-result"><strong>Route edges: {((routeResult.route as Record<string, unknown>).edges as string[] | undefined)?.length ?? 0}</strong><div className="muted">{answer}</div></div>}
        {graph?.source === "osm" && <div className="muted source-note">Imported map: {graph.name}. OSM infrastructure is only simulated where utility assets are mapped.</div>}
      </div>
    </section>
  );
}
