from __future__ import annotations

import asyncio
import json
from typing import Any


class ConnectionManager:
    """WebSocket fan-out to browser clients (the Three.js twin + timeline)."""

    def __init__(self, audit=None) -> None:
        self.audit = audit
        self._clients: set[Any] = set()
        self._lock = asyncio.Lock()
        self.history: list[dict[str, Any]] = []

    async def connect(self, ws: Any) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: Any) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, kind: str, payload: dict[str, Any]) -> None:
        if self.audit:
            scope = "preview" if kind.startswith("command_") or kind in {"whatif", "simulation_complete", "pipeline_preview"} else "live"
            self.audit(kind, payload, scope=scope)
        # envelope kind last: a payload field named "kind" (e.g. an incident's
        # kind) must never shadow the event type clients switch on
        msg = {**payload, "kind": kind}
        self.history.append(msg)
        if len(self.history) > 1000:
            self.history = self.history[-1000:]
        dead = []
        data = json.dumps(msg, default=str)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    def recent(self, n: int = 100) -> list[dict[str, Any]]:
        return self.history[-n:]
