from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..models import CitizenReport, SensorReading, ValidatedSignal
from .trust import score_report, score_sensor


def validate_reading(raw: dict[str, Any]) -> ValidatedSignal | None:
    """Validate a raw sensor payload. Returns a ValidatedSignal or None (bad -> DLQ)."""
    try:
        r = SensorReading(**raw)
    except ValidationError:
        return None
    trust = score_sensor(r)
    return ValidatedSignal(
        source="sensor",
        zone=r.zone,
        kind=r.kind,
        value=r.value,
        entity_ids=[r.sensor_id],
        trust=trust,
        ts=r.ts,
    )


def validate_report(raw: dict[str, Any]) -> ValidatedSignal | None:
    """Validate a citizen report. Only structured fields become a signal;
    the free text is stripped and never reaches an agent/model."""
    try:
        rep = CitizenReport(**raw)
    except ValidationError:
        return None
    trust = score_report(rep)
    kind_map = {
        "flooding": "water_level_cm",
        "blackout": "signal_ok",
        "gridlock": "queue_len",
        "accident": "queue_len",
        "other": "queue_len",
    }
    # a report carries no numeric reading, just a category->signal hint
    return ValidatedSignal(
        source="report",
        zone=rep.zone,
        kind=kind_map.get(rep.category, "queue_len"),
        value=1.0,
        entity_ids=[],
        trust=trust,
        ts=rep.ts,
    )


__all__ = ["validate_reading", "validate_report"]
