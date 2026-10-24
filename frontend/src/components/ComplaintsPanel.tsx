import { useMemo, useState } from "react";
import type { CityGraph, CitySnapshot, CommunityState } from "../types";

interface Props {
  graph: CityGraph | null;
  state: CitySnapshot | null;
  community: CommunityState | null;
  busy: boolean;
  onSubmit: (body: { zone: string; category: "flood" | "blackout" | "pipe_leak" | "traffic"; text: string; count: number; state?: CitySnapshot | null }) => Promise<void>;
}

export default function ComplaintsPanel({ graph, state, community, busy, onSubmit }: Props) {
  const zones = useMemo(() => [...new Set(graph?.nodes.map((node) => node.zone) ?? [])].sort(), [graph]);
  const [zone, setZone] = useState(zones[0] ?? "Z1");
  const [category, setCategory] = useState<"flood" | "blackout" | "pipe_leak" | "traffic">("flood");
  const [count, setCount] = useState("10");
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const submit = async () => {
    setMessage("");
    try {
      await onSubmit({ zone, category, count: Math.max(1, Math.min(100, Number(count) || 1)), text, state });
      setMessage("Complaint influx received. Structured evidence is being checked; text is display-only.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Complaint submission failed.");
    }
  };
  return <section className="panel complaint-panel">
    <header className="panel-head"><span>Area complaint influx</span><span className="muted">untrusted evidence</span></header>
    <div className="panel-body">
      <p className="muted">Send a mass complaint from one area. The agent verifies it against structured sensor/simulation evidence before planning. A complaint alone cannot execute a high-impact action.</p>
      <label>Area<select value={zone} onChange={(event) => setZone(event.target.value)}>{zones.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Topic<select value={category} onChange={(event) => setCategory(event.target.value as typeof category)}><option value="flood">Flooding</option><option value="blackout">Blackout</option><option value="pipe_leak">Pipeline leak</option><option value="traffic">Traffic</option></select></label>
      <label>Complaint count<input type="number" min="1" max="100" value={count} onChange={(event) => setCount(event.target.value)} /></label>
      <label>Message<textarea rows={2} maxLength={2000} placeholder="Residents report water on River Road…" value={text} onChange={(event) => setText(event.target.value)} /></label>
      <button className="btn btn-primary" disabled={busy} onClick={() => void submit()}>Send complaint influx</button>
      {message && <p className="muted">{message}</p>}
      {community && <div className="complaint-summary"><strong>{community.batches.length} batches</strong><span>{community.incidents.filter((item) => item.status === "verified").length} verified</span><span>{community.incidents.filter((item) => item.status === "watch_only").length} watch-only</span></div>}
    </div>
  </section>;
}
