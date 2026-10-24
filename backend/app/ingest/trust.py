from __future__ import annotations

from ..models import CitizenReport, SensorReading

# baseline trust by source type
SENSOR_TRUST = 0.95
REPORT_BASE_TRUST = 0.4

# known-good calibrated sensors (in a real system, learned)
CALIBRATED = {"WL_U1", "PWR_S2", "SIG_J5", "SIG_J6", "SIG_J7"}


def score_sensor(reading: SensorReading) -> float:
    trust = SENSOR_TRUST
    if reading.sensor_id in CALIBRATED:
        trust = min(1.0, trust + 0.03)
    # sanity: clamp physically impossible values -> low trust
    if reading.kind == "water_level_cm" and not (-10 <= reading.value <= 1000):
        trust = 0.1
    if reading.kind == "signal_ok" and reading.value not in (0.0, 1.0):
        trust = 0.2
    return round(trust, 3)


def score_report(report: CitizenReport) -> float:
    """A single citizen report is a weak signal. Repeated, consistent reports
    from trusted reporters accumulate confidence (handled by the aggregator)."""
    return round(max(0.0, min(1.0, report.reporter_trust)), 3)


def combine_trust(scores: list[float]) -> float:
    """Noisy-OR: independent agreeing sources raise confidence fast, but a
    single weak source can't reach the action threshold alone."""
    if not scores:
        return 0.0
    p_none = 1.0
    for s in scores:
        p_none *= 1.0 - s
    return round(1.0 - p_none, 3)


__all__ = ["score_sensor", "score_report", "combine_trust", "REPORT_BASE_TRUST"]
