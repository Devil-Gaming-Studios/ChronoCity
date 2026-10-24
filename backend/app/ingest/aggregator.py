from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from ..models import IncidentSeverity, ValidatedSignal
from .trust import combine_trust


class Aggregator:
    """Reduce a window of signals into per-(zone,kind) summaries.

    This is the 'LLM calls scale with incidents, not data' step: hundreds of
    readings collapse into a handful of aggregated signals before any agent
    is involved.
    """

    def __init__(self, window_seconds: float = 2.0) -> None:
        self.window = window_seconds
        self._buf: dict[tuple[str, str], list[ValidatedSignal]] = defaultdict(list)
        self._last_flush = time.time()

    def add(self, sig: ValidatedSignal) -> None:
        self._buf[(sig.zone, sig.kind)].append(sig)

    def due(self) -> bool:
        return (time.time() - self._last_flush) >= self.window

    def flush(self) -> list[dict[str, Any]]:
        """Return aggregated summaries and clear the buffer."""
        out: list[dict[str, Any]] = []
        now = time.time()
        for (zone, kind), sigs in list(self._buf.items()):
            if not sigs:
                continue
            values = [s.value for s in sigs]
            trusts = [s.trust for s in sigs]
            # entity hint: any signal that referenced concrete entities
            entity_ids: list[str] = []
            for s in sigs:
                for e in s.entity_ids:
                    if e not in entity_ids:
                        entity_ids.append(e)
            sources = {s.source for s in sigs}
            source_counts = {source: sum(1 for sig in sigs if sig.source == source) for source in sources}
            severity = _severity(kind, max(values) if values else 0.0)
            out.append(
                {
                    "zone": zone,
                    "kind": kind,
                    "count": len(sigs),
                    "max": max(values) if values else 0.0,
                    "min": min(values) if values else 0.0,
                    "mean": round(sum(values) / len(values), 3) if values else 0.0,
                    "trust": combine_trust(trusts),
                    "entity_ids": entity_ids,
                    "sources": sorted(sources),
                    "source_counts": source_counts,
                    "report_count": source_counts.get("report", 0),
                    "sensor_count": source_counts.get("sensor", 0),
                    "severity": severity.value,
                    "ts": now,
                }
            )
        self._buf.clear()
        self._last_flush = now
        return out


def _severity(kind: str, peak: float) -> IncidentSeverity:
    if kind == "water_level_cm":
        if peak >= 100:
            return IncidentSeverity.CRITICAL
        if peak >= 50:
            return IncidentSeverity.WARNING
        return IncidentSeverity.INFO
    if kind == "power_draw_kw":
        if peak <= 5000:
            return IncidentSeverity.CRITICAL  # collapse = trip
        if peak >= 40000:
            return IncidentSeverity.WARNING
        return IncidentSeverity.INFO
    if kind == "signal_ok":
        return IncidentSeverity.CRITICAL if peak == 0.0 else IncidentSeverity.INFO
    if kind == "queue_len":
        if peak >= 20:
            return IncidentSeverity.WARNING
        return IncidentSeverity.INFO
    return IncidentSeverity.INFO


__all__ = ["Aggregator"]
