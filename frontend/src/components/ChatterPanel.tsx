import { useEffect, useRef } from "react";
import type { ChronoEvent, CitySnapshot, JointPlan, MapSelection } from "../types";

interface Props {
  events: ChronoEvent[];
  state: CitySnapshot | null;
  plan?: JointPlan | null;
  selection?: MapSelection | null;
  commandText: string;
  commandBusy: boolean;
  setCommandText: (value: string) => void;
  onCommand: (text?: string) => void;
  onOpenOperator?: () => void;
}

const KIND_ICON: Record<string, string> = {
  stage: "·", plan: "·", detected: "·", negotiate: "·", critic: "·", verified: "✓", approval: "✓",
  executed: "✓", incident: "!", whatif: "·", error: "!", command_received: "→", command_parsed: "·",
  command_running: "…", command_response: "←", command_rejected: "!", command_error: "!",
};

function fmt(e: ChronoEvent): string {
  const num = (v: unknown, d = 0) => (typeof v === "number" ? v : d);
  switch (e.kind) {
    case "stage": return "I’m reviewing the city situation with the specialist teams.";
    case "detected": return `I found ${num(e.new)} new incident(s) from the available data.`;
    case "plan": return `The teams prepared ${num(e.actions)} possible response action(s).`;
    case "negotiate": return "I’m coordinating the proposed actions so they do not conflict.";
    case "critic": return e.passed ? "The response passed the safety simulation." : `I found a problem and am revising the response: ${String(e.feedback ?? "")}`;
    case "verified": return e.needs_high_approval ? "The response is checked, but it needs your approval before anything high-impact is applied." : "The response is checked and ready.";
    case "approval": return e.approved ? "You approved the response." : "You rejected the response.";
    case "executed": return `The response was applied to the city twin (${num(e.actions, num(e.executed))} action(s)).`;
    case "incident": return `${String(e.severity ?? "Incident")}: ${String(e.title ?? e.kind)}`;
    case "command_received": return `I received: “${String(e.text ?? "") }”`;
    case "command_parsed": return `I’ll treat that as: ${String(e.intent ?? "a city simulation")}.`;
    case "command_running": return "I’m running that simulation now…";
    case "command_response": return String(e.answer ?? "The simulation is complete.");
    case "command_rejected": return String(e.answer ?? "I could not understand that request.");
    case "command_error": return `I could not complete that request: ${String(e.detail ?? "unknown error")}`;
    case "whatif": return `The what-if result is ${e.passed ? "safe" : "not safe"}.`;
    case "simulation_complete": return "The simulation finished.";
    default: return "I’m updating the city view.";
  }
}

const NOISY = new Set(["hello", "state", "simulation_complete"]);

function isUserEvent(kind: string): boolean {
  return kind === "command_received";
}

export default function ChatterPanel({
  events,
  state,
  plan,
  selection,
  commandText,
  commandBusy,
  setCommandText,
  onCommand,
  onOpenOperator,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const shown = events.filter((event) => !NOISY.has(event.kind)).slice(-60);
  const t = state?.t ?? 0;
  const context = selection ? `${selection.label} (${selection.type})` : "No map item selected";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [shown.length]);

  const quickPrompt = selection?.type === "edge" || selection?.type === "underpass"
    ? "Try: “heavy traffic on the selected road”"
    : "Try: “rain 120 mm”, “trip substation S2”, or “show hospital beds”";

  return (
    <section className="panel panel-chatter chat-app">
      <header className="panel-head">
        <span>City assistant</span>
        <span className="muted">sim t={t.toFixed(0)}s</span>
      </header>
      <div className="chat-context">Talking about: <strong>{context}</strong></div>
      <div className="panel-body chatter-body chat-transcript">
        {shown.length === 0 && <div className="assistant-bubble"><strong>Hi — I can help you explore the city.</strong><span>Choose something on the map, then ask me what-if questions in everyday language.</span></div>}
        {shown.map((event) => (
          <div key={event.id} className={`chat-message ${isUserEvent(event.kind) ? "chat-message-user" : "chat-message-assistant"}`}>
            <div className="chat-avatar">{isUserEvent(event.kind) ? "You" : "AI"}</div>
            <div className="chat-bubble"><span className="chat-text">{fmt(event)}</span><span className="chat-time">{new Date(event.ts * 1000).toLocaleTimeString()}</span></div>
          </div>
        ))}
        {plan?.status === "PENDING_APPROVAL" && (
          <div className="chat-approval-card">
            <strong>This response needs your approval</strong>
            <p className="muted">Review, approve or reject the response in the Operator Dashboard. No actions have been applied.</p>
            <div className="btn-row compact">
              <button className="btn btn-primary" onClick={onOpenOperator}>Open operator review</button>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="chat-composer">
        <div className="chat-hint muted">{quickPrompt}</div>
        <div className="command-row">
          <input
            className="command-input"
            value={commandText}
            onChange={(event) => setCommandText(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") onCommand(); }}
            placeholder={selection ? `Ask about ${selection.label}…` : "Ask about the city…"}
            disabled={commandBusy}
          />
          <button className="btn btn-primary" onClick={() => onCommand()} disabled={commandBusy || !commandText.trim()}>{commandBusy ? "Thinking…" : "Send"}</button>
        </div>
      </div>
    </section>
  );
}
