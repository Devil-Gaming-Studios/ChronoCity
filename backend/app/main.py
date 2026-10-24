from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .agents.orchestrator import Orchestrator
from .agents.workflow import Workflow, adk_available
from .api import cities, commands, incidents, infrastructure, plans, scenarios, simulations, timeline
from .api.ws import ConnectionManager
from .city.build_city import build_demo_city
from .runtime import install_city
from .config import settings
from .ingest.bus import get_bus
from .ingest.api import router as ingest_router


def create_app() -> FastAPI:
    graph = build_demo_city()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- startup ----
        app.state.ws_manager = ConnectionManager()
        install_city(app, graph)
        app.state.bus = get_bus()
        app.state.last_what_if = None
        app.state.ingest_task = None

        async def ingest_loop() -> None:
            """Consume raw readings/reports from the bus, validate, reduce, detect,
            and stream incidents to the frontend. LLM calls are NOT made here."""
            from .ingest.aggregator import Aggregator
            from .ingest.anomaly import AnomalyDetector
            from .ingest.validator import validate_reading, validate_report

            bus = app.state.bus
            agg = Aggregator(window_seconds=settings.window_seconds)
            detector_graph = None
            det = None
            mgr = app.state.ws_manager

            async def consume(topic: str, validator) -> None:
                try:
                    async for raw in bus.subscribe(topic):
                        sig = validator(raw)
                        if sig is None:
                            await bus.publish("dlq", {"topic": topic, "raw": raw})
                            continue
                        agg.add(sig)
                except asyncio.CancelledError:
                    return

            t1 = asyncio.create_task(consume("readings.raw", validate_reading))
            t2 = asyncio.create_task(consume("reports.validated", validate_report))

            # periodic flush -> detect -> broadcast
            try:
                while True:
                    await asyncio.sleep(settings.window_seconds)
                    current_graph = app.state.graph
                    if current_graph is not detector_graph:
                        detector_graph = current_graph
                        det = AnomalyDetector(current_graph, trust_threshold=settings.trust_action_threshold)
                    for summary in agg.flush():
                        for inc in det.detect(summary):
                            if app.state.orchestrator.add_incident(inc):
                                await mgr.broadcast("incident", {
                                    "id": inc.id, "kind": inc.kind, "title": inc.title,
                                    "severity": inc.severity.value, "zone": inc.zone,
                                })
            finally:
                t1.cancel()
                t2.cancel()

        # start the ingest consumer (memory bus is always available)
        app.state.ingest_task = asyncio.create_task(ingest_loop())

        # optional DB schema init (never required for the demo)
        if settings.bus == "redpanda":
            bus = app.state.bus
            if hasattr(bus, "start"):
                try:
                    await bus.start()
                except Exception:  # noqa: BLE001
                    pass

        yield

        # ---- shutdown ----
        task = getattr(app.state, "ingest_task", None)
        if task:
            task.cancel()
        bus = app.state.bus
        if hasattr(bus, "stop"):
            try:
                await bus.stop()
            except Exception:  # noqa: BLE001
                pass

    app = FastAPI(
        title="ChronoTwin API",
        version="0.1.0",
        description="Multi-agent AI operating layer for a city digital twin.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # demo only
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ingest_router)
    app.include_router(cities.router)
    app.include_router(commands.router)
    app.include_router(infrastructure.router)
    app.include_router(incidents.router)
    app.include_router(plans.router)
    app.include_router(simulations.router)
    app.include_router(timeline.router)
    app.include_router(scenarios.router)

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "name": "ChronoTwin",
            "status": "ok",
            "bus": settings.bus,
            "llm_mode": settings.llm_mode,
            "adk": adk_available(),
            "docs": "/docs",
        }

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        mgr: ConnectionManager = app.state.ws_manager
        await mgr.connect(ws)
        try:
            # send a hello with recent history so late joiners catch up
            await ws.send_text(
                __import__("json").dumps(
                    {"kind": "hello", "recent": mgr.recent(50),
                     "state": app.state.orchestrator.state.model_dump()},
                    default=str,
                )
            )
            while True:
                # keep the socket alive; client messages are ignored (server->client stream)
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await mgr.disconnect(ws)

    @app.get("/api/city")
    async def city_graph() -> dict[str, Any]:
        """The active city graph for the Three.js scene and simulation service."""
        return app.state.graph.model_dump()

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "bus": settings.bus, "llm_mode": settings.llm_mode}

    return app


app = create_app()
