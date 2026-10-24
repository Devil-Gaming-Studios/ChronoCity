import { useEffect, useMemo, useState } from "react";
import type { CityGraph, CitySnapshot, CommunityState, MapSelection } from "../types";

type ComplaintCategory = "flood" | "blackout" | "pipe_leak" | "traffic";
type ComplaintSubmission = {
  zone: string;
  category: ComplaintCategory;
  text: string;
  count: number;
  state?: CitySnapshot | null;
  target_id?: string;
  target_type?: "road" | "residential_building";
};

interface Props {
  graph: CityGraph | null;
  selection: MapSelection | null;
  state: CitySnapshot | null;
  community: CommunityState | null;
  busy: boolean;
  onSubmit: (body: ComplaintSubmission) => Promise<Record<string, unknown>>;
}

export default function ComplaintsPanel({ graph, selection, state, community, busy, onSubmit }: Props) {
  const zones = useMemo(() => [...new Set(graph?.nodes.map((node) => node.zone) ?? [])].sort(), [graph]);
  const targets = useMemo(() => [
    ...(graph?.edges.filter((edge) => edge.kind === "road" || edge.kind === "underpass").map((edge) => ({
      id: edge.id, type: "road" as const, label: edge.name || edge.id,
      zone: graph.nodes.find((node) => node.id === edge.src)?.zone ?? graph.nodes.find((node) => node.id === edge.dst)?.zone ?? "",
    })) ?? []),
    ...(graph?.buildings?.filter((building) => ["residential", "house", "apartments", "detached", "semidetached_house", "terrace", "yes"].includes((building.kind || building.tags?.building || "").toLowerCase())).map((building) => ({
      id: building.id, type: "residential_building" as const, label: building.name || building.id,
      zone: building.tags?.zone ?? (graph.source === "osm" ? "OSM" : ""),
    })) ?? []),
  ], [graph]);
  const [zone, setZone] = useState(zones[0] ?? "Z1");
  const [targetKey, setTargetKey] = useState("");
  const [category, setCategory] = useState<"flood" | "blackout" | "pipe_leak" | "traffic">("flood");
  const [count, setCount] = useState("10");
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [actions, setActions] = useState<Array<Record<string, unknown>>>([]);
  const selectedTarget = targets.find((item) => `${item.type}:${item.id}` === targetKey);
  useEffect(() => {
    if (zones.length && !zones.includes(zone)) setZone(zones[0]);
  }, [zone, zones]);
  useEffect(() => {
    const mappedType = selection?.type === "building" ? "residential_building" : ["edge", "underpass"].includes(selection?.type ?? "") ? "road" : undefined;
    const mapped = mappedType && selection ? targets.find((item) => item.type === mappedType && item.id === selection.id) : undefined;
    if (mapped) {
      setTargetKey(`${mapped.type}:${mapped.id}`);
      if (mapped.zone) setZone(mapped.zone);
    }
  }, [selection, targetKey, targets]);
  useEffect(() => {
    if (selectedTarget?.zone) setZone(selectedTarget.zone);
  }, [selectedTarget?.zone]);
  const submit = async () => {
    setMessage("");
    setActions([]);
    try {
      const result = await onSubmit({ zone, category, count: Math.max(1, Math.min(100, Number(count) || 1)), text, state,
        target_id: selectedTarget?.id, target_type: selectedTarget?.type });
      const action = result.agent_action as { status?: string; message?: string; actions?: unknown[] } | undefined;
      const proposed = Array.isArray(action?.actions) ? action.actions.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [];
      setActions(proposed);
      setMessage(action?.message
        ? `Complaint influx logged. ${action.message}`
        : "Complaint influx logged. Structured evidence is being checked; text is display-only.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Complaint submission failed.");
    }
  };
  return <section className="panel complaint-panel">
    <header className="panel-head"><span>Simulate complaints</span><span className="muted">agent handoff · audit recorded</span></header>
    <div className="panel-body">
      <p className="muted">Choose a road or residential building, set the complaint volume and issue, then send the structured event to the backend agents. Their proposed actions are recorded for operator review; nothing changes live until approval and execution.</p>
      <label>Complaint target<select value={targetKey} onChange={(event) => setTargetKey(event.target.value)} disabled={!targets.length}>
        {!targets.length && <option value="">No roads or residential buildings available</option>}
        {targets.map((item) => <option key={`${item.type}:${item.id}`} value={`${item.type}:${item.id}`}>{item.type === "road" ? "Road" : "Residential building"}: {item.label}</option>)}
      </select></label>
      <label>Region<select value={zone} onChange={(event) => setZone(event.target.value)}>{zones.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Topic<select value={category} onChange={(event) => setCategory(event.target.value as typeof category)}><option value="flood">Flooding</option><option value="blackout">Blackout</option><option value="pipe_leak">Pipeline leak</option><option value="traffic">Traffic</option></select></label>
      <label>Complaint count<input type="number" min="1" max="100" value={count} onChange={(event) => setCount(event.target.value)} /></label>
      <label>Resident message<textarea rows={2} maxLength={2000} placeholder="Residents report water on River Road…" value={text} onChange={(event) => setText(event.target.value)} /></label>
      <button className="btn btn-primary" disabled={busy || !zones.length || !selectedTarget} onClick={() => void submit()}>{busy ? "Sending to agents…" : "Simulate complaints"}</button>
      {message && <p className="muted">{message}</p>}
      {actions.length > 0 && <div className="complaint-actions"><strong>Recorded response actions</strong><ol>{actions.map((item, index) => <li key={`${String(item.tool)}-${index}`}><code>{String(item.tool)}</code> · {Array.isArray(item.entity_ids) ? item.entity_ids.join(", ") : "target selected by agent"}<span className="muted">{item.rationale ? ` — ${String(item.rationale)}` : ""}</span></li>)}</ol></div>}
      {community && <div className="complaint-summary"><strong>{community.batches.length} events</strong><span>{community.incidents.filter((item) => item.status === "verified" || item.status === "inferred" || item.status === "planned").length} issues tracked</span><span>{community.batches.filter((item) => item.verification_status === "watch_only").length} watch-only</span></div>}
    </div>
  </section>;
}
