import { useEffect, useRef } from "react";
import type { ChronoEvent, CitySnapshot } from "../types";

interface Props {
  events: ChronoEvent[];
  state: CitySnapshot | null;
}

const KIND_ICON: Record<string, string> = {
  stage: "»",
  plan: "◇",
  detected: "◉",
  negotiate: "⇄",
  critic: "⚖",
  verified: "✔",
  approval: "✋",
  executed: "▶",
  incident: "⚠",
  whatif: "⌁",
  error: "✕",
};

function fmt(e: ChronoEvent): string {
  const num = (v: unknown, d = 0) => (typeof v === "number" ? v : d);
  switch (e.kind) {
    case "stage":
      return `Planning: ${(e.agents as string[] | undefined)?.join(", ") ?? "specialists"} engaged`;
    case "detected":
      return `Code reduced raw telemetry → ${num(e.new)} new incident(s)`;
    case "plan":
      return `Specialists proposed ${num(e.actions)} action(s), ${num(e.conflicts)} conflict(s)`;
    case "negotiate":
      return `Negotiator: ${num(e.conflicts)} conflict(s) — ${String(e.resolution ?? "")}`;
    case "critic":
      return e.passed
        ? `Critic v${num(e.iteration)}: simulation PASSED`
        : `Critic v${num(e.iteration)}: REVISION — ${String(e.feedback ?? "")}`;
    case "verified":
      return e.needs_high_approval
        ? "Plan verified — HIGH-impact actions need human approval"
        : `Plan verified (${String(e.status ?? "")}) — awaiting approval`;
    case "approval":
      return `Human ${e.approved ? "approved" : "rejected"} the plan`;
    case "executed":
      return `Executed ${num(e.actions, num(e.executed))} action(s) on the twin`;
    case "incident":
      return `Incident [${String(e.severity ?? "")}] ${String(e.title ?? e.kind)}`;
    case "whatif":
      return `What-if "${String(e.label ?? "")}" simulated — ${e.passed ? "passed" : "failed"} (score ${num(e.score).toFixed(2)})`;
    case "error":
      return `Error: ${String(e.detail ?? e.error ?? "")}`;
    default:
      return e.kind;
  }
}

const NOISY = new Set(["hello", "state"]);

export default function ChatterPanel({ events, state }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const shown = events.filter((e) => !NOISY.has(e.kind)).slice(-60);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [shown.length]);

  const t = state?.t ?? 0;

  return (
    <section className="panel panel-chatter">
      <header className="panel-head">
        <span>Agent Chatter</span>
        <span className="muted">sim t={t.toFixed(0)}s</span>
      </header>
      <div className="panel-body chatter-body">
        {shown.length === 0 && (
          <p className="muted">Live agent stream will appear here over the WebSocket.</p>
        )}
        {shown.map((e) => (
          <div key={e.id} className={`chat-line chat-${e.kind}`}>
            <span className="chat-time">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
            <span className="chat-icon">{KIND_ICON[e.kind] ?? "·"}</span>
            <span className="chat-text">{fmt(e)}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}
