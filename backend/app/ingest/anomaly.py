from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Anomaly, CityGraph, Incident, IncidentSeverity


class AnomalyDetector:
    """Turn aggregated signals into concrete Incidents.

    Pure code, no LLM. Threshold rules + a simple z-score over a rolling window.
    Reports cannot alone create an action-triggering incident below the trust gate.
    """

    def __init__(self, graph: CityGraph, trust_threshold: float = 0.5) -> None:
        self.graph = graph
        self.trust_threshold = trust_threshold
        self._history: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._seen_dedupe: set[str] = set()
        self.watch_alerts: list[dict[str, Any]] = []

    def _zscore(self, key: tuple[str, str], value: float) -> float:
        hist = self._history[key]
        hist.append(value)
        if len(hist) > 50:
            hist.pop(0)
        if len(hist) < 3:
            return 0.0
        mean = sum(hist) / len(hist)
        var = sum((h - mean) ** 2 for h in hist) / len(hist)
        std = var ** 0.5
        if std == 0:
            return 0.0
        return (value - mean) / std

    def detect(self, agg: dict[str, Any] | list[dict[str, Any]]) -> list[Incident]:
        # The bus loop sends one summary at a time; tests and integrations may
        # hand us the complete Aggregator.flush() list. Support both forms.
        if isinstance(agg, list):
            incidents: list[Incident] = []
            for summary in agg:
                incidents.extend(self.detect(summary))
            return incidents

        zone = agg["zone"]
        kind = agg["kind"]
        peak = agg["max"]
        trust = agg["trust"]
        entity_ids = agg.get("entity_ids", [])
        incidents: list[Incident] = []

        key = (zone, kind)
        z = self._zscore(key, peak)

        sources = set(agg.get("sources", []))
        if sources == {"report"}:
            # A citizen report alone can never create an actionable incident.
            self.watch_alerts.append({"zone": zone, "kind": kind, "trust": trust, "reason": "report-only evidence", "ts": agg.get("ts")})
            return []
        if trust < self.trust_threshold:
            # weak signal: record a watch alert but do NOT create an actionable incident
            self.watch_alerts.append({"zone": zone, "kind": kind, "trust": trust, "reason": "below trust threshold", "ts": agg.get("ts")})
            return []

        if kind == "water_level_cm" and peak >= 100:
            inc = self._flood(zone, entity_ids, peak, trust)
            incidents.append(inc)
        elif kind == "power_draw_kw" and agg.get("min", peak) <= 5000:
            # a trip is a *collapse* in draw; use the window minimum
            inc = self._trip(zone, entity_ids, trust)
            incidents.append(inc)
        elif kind == "signal_ok" and peak == 0.0:
            inc = self._signal_dark(zone, entity_ids, trust)
            incidents.append(inc)
        elif kind == "queue_len" and peak >= 20:
            inc = self._gridlock(zone, entity_ids, peak, trust)
            incidents.append(inc)
        elif z >= 3.0:
            incidents.append(
                Incident(
                    kind="gridlock",
                    severity=IncidentSeverity.WARNING,
                    zone=zone,
                    entity_ids=entity_ids,
                    title=f"Anomalous {kind} in {zone}",
                    detail=f"z={z:.1f}, peak={peak}",
                    priority=4,
                    trust=trust,
                    dedupe_key=f"anom:{zone}:{kind}",
                )
            )

        # dedupe within a window
        fresh: list[Incident] = []
        for inc in incidents:
            if inc.dedupe_key in self._seen_dedupe:
                continue
            self._seen_dedupe.add(inc.dedupe_key)
            inc.evidence_sources = sorted(sources)
            inc.watch_only = False
            fresh.append(inc)
        return fresh

    def _flood(self, zone, entity_ids, peak, trust) -> Incident:
        edge = entity_ids[0] if entity_ids else "E_J4_J6_U1"
        up = next((u for u in self.graph.underpasses if u.edge_id == edge), None)
        return Incident(
            kind="flood",
            severity=IncidentSeverity.CRITICAL,
            zone=zone,
            entity_ids=[edge] + ([up.id] if up else []),
            title=f"Underpass flooding: {up.name if up else edge}",
            detail=f"Water {peak:.0f}cm; edge {edge} impassable.",
            priority=1,
            trust=trust,
            dedupe_key=f"flood:{up.id if up else edge}",
        )

    def _trip(self, zone, entity_ids, trust) -> Incident:
        sid = entity_ids[0] if entity_ids else "S2"
        sub = next((s for s in self.graph.substations if s.id == sid), None)
        if sub is None:
            # sensor id like PWR_S2 -> substation S2
            guess = sid.split("_")[-1] if "_" in sid else sid
            sub = next((s for s in self.graph.substations if s.id == guess), None)
            if sub is not None:
                sid = sub.id
        dark = [sig.id for sig in self.graph.signals if sub and sig.feeder_id in sub.feeders]
        return Incident(
            kind="substation_trip",
            severity=IncidentSeverity.CRITICAL,
            zone=zone,
            entity_ids=[sid] + dark,
            title=f"Substation {sid} trip",
            detail=f"Feeders down; signals dark: {', '.join(dark)}.",
            priority=1,
            trust=trust,
            dedupe_key=f"trip:{sid}",
        )

    def _signal_dark(self, zone, entity_ids, trust) -> Incident:
        sid = entity_ids[0] if entity_ids else ""
        return Incident(
            kind="signal_dark",
            severity=IncidentSeverity.WARNING,
            zone=zone,
            entity_ids=entity_ids or [sid],
            title=f"Signal dark: {sid}",
            detail=f"Signal {sid} lost power in {zone}.",
            priority=3,
            trust=trust,
            dedupe_key=f"dark:{sid}",
        )

    def _gridlock(self, zone, entity_ids, peak, trust) -> Incident:
        return Incident(
            kind="gridlock",
            severity=IncidentSeverity.WARNING,
            zone=zone,
            entity_ids=entity_ids,
            title=f"Gridlock in {zone}",
            detail=f"Queue length {peak:.0f}.",
            priority=3,
            trust=trust,
            dedupe_key=f"gridlock:{zone}",
        )


__all__ = ["AnomalyDetector"]
