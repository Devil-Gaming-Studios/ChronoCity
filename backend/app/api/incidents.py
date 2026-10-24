from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..city.cascade import trace_cascade
from ..models import CitySnapshot, Incident

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(request: Request) -> list[dict[str, Any]]:
    orch = request.app.state.orchestrator
    return [
        {
            "id": i.id,
            "kind": i.kind,
            "severity": i.severity.value,
            "zone": i.zone,
            "title": i.title,
            "detail": i.detail,
            "priority": i.priority,
            "trust": i.trust,
            "resolved": i.resolved,
            "entity_ids": i.entity_ids,
            "created_ts": i.created_ts,
        }
        for i in orch.incidents
    ]


@router.get("/cascade")
async def cascade(request: Request) -> dict[str, Any]:
    """Cascade view: hops from the root failure(s) over the current state."""
    app = request.app
    graph = app.state.graph
    state: CitySnapshot = app.state.orchestrator.state
    dark_nodes = {s.node_id for s in graph.signals if not state.signals_ok.get(s.id, True)}
    blocked = set(state.flooded_edges.keys()) | set(state.closed_edges.keys())
    # root failures are the physical blockages; dark junctions are consequences
    roots: list[str] = sorted(blocked)
    if not roots:
        roots = sorted(dark_nodes)
    if not roots:
        return {"roots": [], "hops": [], "contained_hops": 0, "affected": []}
    return trace_cascade(graph, roots, blocked_edges=blocked, dark_nodes=dark_nodes)


@router.get("/state")
async def city_state(request: Request) -> dict[str, Any]:
    orch = request.app.state.orchestrator
    return orch.state.model_dump()
