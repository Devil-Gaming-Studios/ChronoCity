import type { CityGraph, HospitalInfo, MapSelection } from "../types";

interface Props {
  graph: CityGraph | null;
  selection: MapSelection | null;
  hospital: HospitalInfo | null;
  diagnostics: Record<string, unknown> | null;
  routeResult: Record<string, unknown> | null;
  onPreviewSelection: () => void;
  onQuickCommand: (text: string) => void;
  onRoute: (vehicleType: "firetruck" | "police" | "ambulance") => void;
}

const friendlyType: Record<string, string> = {
  edge: "Road",
  underpass: "Underpass road",
  hospital: "Hospital",
  substation: "Power station",
  power_line: "Power line",
  pipeline: "Water pipeline",
  waterway: "Waterway",
  water_works: "Water facility",
  wastewater_plant: "Wastewater facility",
  building: "Building",
};

export default function ControlPanel({
  graph,
  selection,
  hospital,
  diagnostics,
  routeResult,
  onPreviewSelection,
  onQuickCommand,
  onRoute,
}: Props) {
  const station = diagnostics?.probable_station as Record<string, unknown> | undefined;
  const stations = Array.isArray(diagnostics?.stations) ? diagnostics.stations as Record<string, unknown>[] : [];
  const routeAnswer = String(routeResult?.answer ?? "");
  const route = routeResult?.route as { reachable?: boolean } | undefined;
  const selectedEdge = selection && ["edge", "underpass"].includes(selection.type)
    ? graph?.edges.find((edge) => edge.id === selection.id)
    : null;
  const selectedAsset = selection && graph?.infrastructure?.find((asset) => asset.id === selection.id);
  const canPreview = Boolean(selection && ["edge", "underpass", "power_line"].includes(selection.type));

  return (
    <section className="panel panel-controls">
      <header className="panel-head">
        <span>Selected map item</span>
        <span className="muted">click the map to choose</span>
      </header>
      <div className="panel-body">
        <div className="control-help muted">
          Click a colored road, hospital, power station, or utility line. Then ask the City assistant to simulate a change.
        </div>

        <div className="selection-card">
          {selection ? (
            <>
              <div className="selection-kind">{friendlyType[selection.type] ?? selection.type}</div>
              <div className="selected-title">{selection.label}</div>
              {selectedEdge && (
                <p className="selection-description">
                  {selectedEdge.name || "Unnamed road"} · {selectedEdge.lanes} lane{selectedEdge.lanes === 1 ? "" : "s"} · {Math.round(selectedEdge.length_m)} m
                </p>
              )}
              {selectedAsset && <p className="selection-description">Mapped utility asset · {selectedAsset.name || "unnamed"}</p>}
              <div className="chips"><span className="chip chip-entity">{selection.id}</span></div>

              {selectedEdge && (
                <div className="quick-actions">
                  <span className="muted quick-label">Quick actions</span>
                  <button className="btn" onClick={() => onQuickCommand("heavy traffic on the selected road")}>Heavy traffic</button>
                  <button className="btn" onClick={() => onQuickCommand("close the selected road")}>Close road</button>
                  <button className="btn" onClick={() => onQuickCommand("flood the selected road")}>Flood road</button>
                </div>
              )}
               {canPreview && <button className="btn btn-warn" onClick={onPreviewSelection}>Preview disable</button>}
              {(selection.type === "substation" || selection.type === "pipeline") && (
                <p className="floating-card-hint">Use the floating control card above the selected structure to edit readings or disable the asset.</p>
              )}

              {(selection.type === "hospital" || selection.type === "edge" || selection.type === "underpass") && (
                <div className="btn-row compact">
                  <button className="btn" onClick={() => onRoute("firetruck")}>Plan firetruck route</button>
                  <button className="btn" onClick={() => onRoute("police")}>Plan police route</button>
                  {(selection.type === "hospital" || selection.type === "edge" || selection.type === "underpass") && <button className="btn" onClick={() => onRoute("ambulance")}>Plan ambulance route</button>}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="selection-kind">No map item selected</div>
              <p className="muted">Choose a road or utility asset in the 3D map to give the assistant a specific target.</p>
            </>
          )}
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

        {diagnostics?.domain === "power" && (
          <div className="diagnostic-card">
            <h4>Power production and outage regions</h4>
            {station && <div><span className="muted">Likely station:</span> {String(station.substation_id)} · {String(station.status)}</div>}
            {stations.map((item) => <div className="power-station-row" key={String(item.substation_id)}><strong>{String(item.substation_id)}</strong><span>{String(item.generation_mw)} MW produced · {String(item.load_mw)} MW load</span><span className={`badge ${item.status === "healthy" ? "badge-ok" : "badge-critical"}`}>{String(item.status)}</span></div>)}
            <div className="outage-regions"><span className="muted">Affected regions:</span> {Array.isArray(diagnostics?.affected_zones) && diagnostics.affected_zones.length ? diagnostics.affected_zones.join(", ") : "none"}</div>
            {Array.isArray(diagnostics?.affected_nodes) && diagnostics.affected_nodes.length > 0 && <div className="muted">Dark nodes: {diagnostics.affected_nodes.join(", ")}</div>}
          </div>
        )}

        {routeAnswer && <div className="control-result"><strong>{routeAnswer}</strong></div>}
        {route?.reachable && <div className="control-result"><strong>Route ready</strong><div className="muted">The yellow path uses the displayed snapshot and avoids blocked roads.</div></div>}
        {graph?.source === "osm" && <div className="muted source-note">Map: {graph.name}. Utility behavior is simulated only where assets are mapped.</div>}
      </div>
    </section>
  );
}
