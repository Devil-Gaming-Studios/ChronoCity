from __future__ import annotations

from typing import Any
import hashlib
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..models import CitizenReport, SensorReading

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
_RATE: dict[str, list[float]] = {}
_REPORT_DEDUPE: dict[str, float] = {}


def _guard(api_key: str | None, client: str) -> None:
    if settings.ingest_api_key and api_key != settings.ingest_api_key:
        raise HTTPException(status_code=401, detail="invalid ingest api key")
    now = time.time()
    bucket = [t for t in _RATE.get(client, []) if now - t < 60]
    if len(bucket) >= settings.ingest_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="ingest rate limit exceeded")
    bucket.append(now)
    _RATE[client] = bucket


class SensorBatch(BaseModel):
    readings: list[SensorReading]


@router.post("/sensor")
async def ingest_sensor(reading: SensorReading, request: Request, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    """Accept a raw sensor reading onto the bus."""
    _guard(x_api_key, request.client.host if request.client else "unknown")
    bus = request.app.state.bus
    await bus.publish("readings.raw", reading.model_dump(), key=reading.zone)
    return {"ok": True, "id": reading.id}


@router.post("/sensor/batch")
async def ingest_sensor_batch(body: SensorBatch, request: Request, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    _guard(x_api_key, request.client.host if request.client else "unknown")
    bus = request.app.state.bus
    for reading in body.readings:
        await bus.publish("readings.raw", reading.model_dump(), key=reading.zone)
    return {"ok": True, "accepted": len(body.readings)}


@router.post("/report")
async def ingest_report(report: CitizenReport, request: Request, x_api_key: str | None = Header(default=None), x_captcha_token: str | None = Header(default=None)) -> dict[str, Any]:
    """Accept a citizen report. Free text is stored, never prompted."""
    _guard(x_api_key, request.client.host if request.client else "unknown")
    if settings.captcha_required and x_captcha_token != settings.captcha_demo_token:
        raise HTTPException(status_code=400, detail="captcha verification required")
    fingerprint = hashlib.sha256(f"{report.category}|{report.zone}|{round(report.lat, 4)}|{round(report.lon, 4)}".encode()).hexdigest()
    now = time.time()
    if fingerprint in _REPORT_DEDUPE and now - _REPORT_DEDUPE[fingerprint] < settings.dedupe_window_s:
        return {"ok": True, "duplicate": True, "id": report.id}
    _REPORT_DEDUPE[fingerprint] = now
    bus = request.app.state.bus
    # store the full report (with text) for audit, but publish structured-only
    payload = report.model_dump(exclude={"text"})
    await bus.publish("reports.validated", payload, key=report.zone)
    return {"ok": True, "id": report.id}


@router.get("/health")
async def ingest_health(request: Request) -> dict[str, Any]:
    bus = request.app.state.bus
    return {"bus": type(bus).__name__, "ok": True}
