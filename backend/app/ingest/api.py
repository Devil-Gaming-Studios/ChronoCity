from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..models import CitizenReport, SensorReading

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/sensor")
async def ingest_sensor(reading: SensorReading, request: Request) -> dict[str, Any]:
    """Accept a raw sensor reading onto the bus."""
    bus = request.app.state.bus
    await bus.publish("readings.raw", reading.model_dump(), key=reading.zone)
    return {"ok": True, "id": reading.id}


@router.post("/report")
async def ingest_report(report: CitizenReport, request: Request) -> dict[str, Any]:
    """Accept a citizen report. Free text is stored, never prompted."""
    bus = request.app.state.bus
    # store the full report (with text) for audit, but publish structured-only
    payload = report.model_dump(exclude={"text"})
    await bus.publish("reports.validated", payload, key=report.zone)
    return {"ok": True, "id": report.id}


@router.get("/health")
async def ingest_health(request: Request) -> dict[str, Any]:
    bus = request.app.state.bus
    return {"bus": type(bus).__name__, "ok": True}
