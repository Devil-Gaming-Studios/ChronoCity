import { useState } from "react";
import type { CityGraph, MapSelection, PowerDiagnostics, RouteRequest } from "../types";
import type { ViewMode } from "./TwinScene";

interface Props {
  graph: CityGraph | null;
  selectedItems: MapSelection[];
  onSelectionChange: (items: MapSelection[]) => void;
  busy: boolean;
  onPreview: (hazards: Array<Record<string, unknown>>) => Promise<void>;
  power: PowerDiagnostics | null;
  routeConfig: RouteRequest | null;
  onRouteChange: (route: RouteRequest) => void;
  routeResult: Record<string, unknown> | null;
  viewMode: ViewMode;
  onClearPreview: () => void;
}

export default function SimulationPanel(props: Props) {
  const { graph, selectedItems, onSelectionChange, busy, onPreview, power, routeConfig, onRouteChange, routeResult } = props;
  const [depth, setDepth] = useState("100");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [powerEdits, setPowerEdits] = useState<Record<string, { supply: string; load: string }>>({});
  if (!graph) return null;
  const nodes = graph.nodes.filter((node) => node.kind !== "substation");
  const options: MapSelection[] = [
    ...graph.edges.filter((edge) => edge.kind !== "feeder").map((edge) => ({ id: edge.id, type: "edge", label: edge.name || edge.id })),
    ...nodes.map((node) => ({ id: node.id, type: node.kind, label: node.name || node.id })),
  ];
  const route = routeResult?.route as { reachable: boolean; edges: string[]; travel_s: number | null } | undefined;
  const run = async (hazards: Array<Record<string, unknown>>) => {
    setError("");
    try { await onPreview(hazards); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Simulation failed"); }
  };
  const disrupt = (kind: "disable" | "flood" | "traffic") => {
    const roads = selectedItems.filter((item) => ["edge", "underpass"].includes(item.type)).map((item) => item.id);
    const nodeIds = selectedItems.filter((item) => ["junction", "hospital", "depot", "shelter"].includes(item.type))
      .map((item) => item.type === "hospital" ? graph.hospitals.find((h) => h.id === item.id)?.node_id ?? item.id : item.id);
    const stations = selectedItems.filter((item) => item.type === "substation").map((item) => item.id);
    if (kind === "flood" && (!Number.isFinite(Number(depth)) || Number(depth) <= 0)) {
      setError("Enter a flood depth greater than zero."); return;
    }
    const hazards: Array<Record<string, unknown>> = [];
    if (roads.length) hazards.push({ type: kind === "disable" ? "close_edge" : kind === "flood" ? "flood" : "heavy_traffic", edge_ids: roads, depth_cm: Number(depth), congestion_factor: 3 });
    if (nodeIds.length && kind !== "traffic") hazards.push({ type: kind === "flood" ? "flood_node" : "disable_node", node_ids: nodeIds, depth_cm: Number(depth) });
    if (stations.length && kind === "disable") hazards.push({ type: "power_outage", substation_ids: stations });
    if (!hazards.length) { setError("Choose supported roads/nodes, or stations to disable."); return; }
    void run(hazards);
  };

  return <section className="panel simulation-panel">
    <header className="panel-head">Simulation controls · {props.viewMode}</header>
    <div className="panel-body">
      <p className="muted">Changes build on the displayed snapshot in a private what-if preview. Live state is unchanged.</p>
      <button className="btn" disabled={busy} onClick={props.onClearPreview}>Discard preview</button>
      <h4>Automatic emergency route</h4>
      <label>Vehicle<select value={routeConfig?.vehicle_type ?? "ambulance"} onChange={(event) => {
        if (routeConfig) onRouteChange({ ...routeConfig, vehicle_type: event.target.value as RouteRequest["vehicle_type"] });
      }}><option value="ambulance">Ambulance</option><option value="firetruck">Firetruck</option><option value="police">Police</option></select></label>
      {(["origin", "destination_node"] as const).map((field) => <label key={field}>
        {field === "origin" ? "From" : "To"}
        <select value={routeConfig?.[field] ?? ""} onChange={(event) => onRouteChange({
          vehicle_type: routeConfig?.vehicle_type ?? "ambulance",
          origin: routeConfig?.origin ?? nodes[0]?.id ?? "",
          destination_node: routeConfig?.destination_node ?? graph.hospitals[0]?.node_id ?? nodes[0]?.id ?? "",
          [field]: event.target.value,
        })}>
          <option value="" disabled>Choose a mapped node</option>
          {nodes.map((node) => <option key={node.id} value={node.id}>{node.name || node.id} ({node.id})</option>)}
        </select>
      </label>)}
      <div role="status" className="control-result">
        {routeResult ? String(routeResult.answer) : routeConfig ? "Recalculating route…" : "Choose an origin and destination."}
        {route?.reachable && <span className="muted">Yellow path · {route.edges.length} roads · automatically updated after disruptions</span>}
        {route && !route.reachable && <strong>No safe route — the map does not show a stale path.</strong>}
      </div>

      <h4>Multiple road / node disruptions</h4>
      <p className="muted">Shift-click map items, or use this list. You can combine closures, floods, traffic and station outages.</p>
      <input aria-label="Filter roads and nodes" placeholder="Filter roads and nodes" value={filter} onChange={(event) => setFilter(event.target.value)} />
      <div className="simulation-targets">
        {options.filter((item) => `${item.id} ${item.label}`.toLowerCase().includes(filter.toLowerCase())).map((item) => <label key={item.id}>
          <input type="checkbox" checked={selectedItems.some((selected) => selected.id === item.id)} onChange={(event) => {
            onSelectionChange(event.target.checked ? [...selectedItems, item] : selectedItems.filter((selected) => selected.id !== item.id));
          }} />{item.type === "edge" ? "Road" : "Node"}: {item.label}
        </label>)}
      </div>
      <p>{selectedItems.length} selected <button className="btn btn-small" onClick={() => onSelectionChange([])}>Clear selection</button></p>
      <label>Flood depth (cm)<input type="number" min="1" value={depth} onChange={(event) => setDepth(event.target.value)} /></label>
      <div className="btn-row compact">
        <button className="btn" disabled={busy || !selectedItems.length} onClick={() => disrupt("disable")}>Disable selected</button>
        <button className="btn" disabled={busy || !selectedItems.length} onClick={() => disrupt("flood")}>Flood selected</button>
        <button className="btn" disabled={busy || !selectedItems.length} onClick={() => disrupt("traffic")}>Heavy traffic</button>
      </div>
      <h4>Station power readings (MW)</h4>
      <p className="muted">Simulated supply/output, not measured electricity generation. Substations distribute power.</p>
      {power?.stations.map((station) => {
        const edits = powerEdits[station.substation_id] ?? { supply: String(station.generation_mw), load: String(station.load_mw) };
        const valid = edits.supply.trim() !== "" && edits.load.trim() !== "" && Number.isFinite(Number(edits.supply)) && Number.isFinite(Number(edits.load))
          && Number(edits.supply) >= 0 && Number(edits.load) >= 0 && Number(edits.supply) <= station.capacity_mw;
        return <fieldset key={station.substation_id} className="station-editor" disabled={busy}>
          <legend>{station.substation_id} · {station.status.split("_").join(" ")}</legend>
          <strong>Output {station.output_mw} MW · Load {station.load_mw} MW</strong>
          <div className="muted">Available supply {station.generation_mw} MW · Capacity {station.capacity_mw} MW</div>
          <label>Supply MW<input type="number" min="0" max={station.capacity_mw} step="0.1" value={edits.supply}
            onChange={(event) => setPowerEdits((current) => ({ ...current, [station.substation_id]: { ...edits, supply: event.target.value } }))} /></label>
          <label>Load MW<input type="number" min="0" step="0.1" value={edits.load}
            onChange={(event) => setPowerEdits((current) => ({ ...current, [station.substation_id]: { ...edits, load: event.target.value } }))} /></label>
          {!valid && <span role="alert">Use non-negative MW values; supply cannot exceed capacity.</span>}
          <div className="btn-row compact">
            <button className="btn btn-primary" disabled={!valid} onClick={() => void run([
              { type: "power_generation", substation_id: station.substation_id, generation_mw: Number(edits.supply) },
              { type: "power_overload", substation_id: station.substation_id, load_mw: Number(edits.load) },
            ])}>Preview readings</button>
            <button className="btn btn-danger" onClick={() => void run([{ type: "power_outage", substation_id: station.substation_id }])}>Trip</button>
            <button className="btn" onClick={() => void run([{ type: "power_restore", substation_id: station.substation_id }])}>Restore</button>
          </div>
        </fieldset>;
      })}
      {power && !power.stations.length && <p>No mapped stations are available in this city.</p>}
      <div className="control-result">
        <strong>Affected power zones: {power ? power.affected_zones.join(", ") || "none" : "loading…"}</strong>
        <span>Service points: {power?.affected_nodes.join(", ") || "none"}</span>
        <span className="muted">Red rings show affected mapped service points, not a surveyed outage boundary.</span>
      </div>
      {error && <p role="alert" className="badge-critical">{error}</p>}
    </div>
  </section>;
}
