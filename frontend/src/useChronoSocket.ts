import { useEffect, useRef, useState } from "react";
import type { ChronoEvent, CitySnapshot } from "./types";

export interface ChronoSocket {
  connected: boolean;
  events: ChronoEvent[];
  state: CitySnapshot | null;
}

let seq = 0;

/** Server -> client stream of pipeline stages + twin state. */
export function useChronoSocket(onEvent?: (e: ChronoEvent) => void): ChronoSocket {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<ChronoEvent[]>([]);
  const [state, setState] = useState<CitySnapshot | null>(null);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (msg) => {
        try {
          const raw = JSON.parse(msg.data) as Record<string, unknown>;
          const e: ChronoEvent = {
            ...raw,
            id: `e${++seq}`,
            ts: Date.now() / 1000,
            kind: String(raw.kind ?? "message"),
          };
          if (e.kind === "hello" && e.state) setState(e.state as CitySnapshot);
          if (e.kind === "state" && e.state) setState(e.state as CitySnapshot);
          setEvents((prev) => [...prev.slice(-199), e]);
          handler.current?.(e);
        } catch {
          /* ignore malformed frames */
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return { connected, events, state };
}
