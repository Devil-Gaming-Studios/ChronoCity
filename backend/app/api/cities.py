from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..city.osm import DEFAULT_OVERPASS_URL, OSM_ATTRIBUTION, import_osm_bbox
from ..runtime import install_city

router = APIRouter(prefix="/api/cities", tags=["cities"])


class OSMImportRequest(BaseModel):
    south: float = Field(..., ge=-90, le=90)
    west: float = Field(..., ge=-180, le=180)
    north: float = Field(..., ge=-90, le=90)
    east: float = Field(..., ge=-180, le=180)
    name: str = "OpenStreetMap area"
    overpass_url: str = DEFAULT_OVERPASS_URL


@router.get("/current")
async def current_city(request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    return {
        "name": graph.name,
        "source": graph.source,
        "source_ref": graph.source_ref,
        "bounds": graph.bounds,
        "attribution": graph.attribution,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "buildings": len(graph.buildings),
        "infrastructure": len(graph.infrastructure),
        "hospitals": len(graph.hospitals),
    }


@router.post("/import/osm")
async def import_osm(body: OSMImportRequest, request: Request) -> dict[str, Any]:
    """Replace the active city with roads/buildings/assets from an OSM bbox."""
    try:
        graph = await import_osm_bbox(
            body.south,
            body.west,
            body.north,
            body.east,
            name=body.name,
            overpass_url=body.overpass_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenStreetMap query failed: {exc}") from exc

    if not graph.edges:
        raise HTTPException(status_code=422, detail="The selected OSM area contained no drivable roads")

    install_city(request.app, graph)
    await request.app.state.ws_manager.broadcast(
        "city_loaded",
        {
            "name": graph.name,
            "source": graph.source,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "buildings": len(graph.buildings),
            "infrastructure": len(graph.infrastructure),
        },
    )
    await request.app.state.ws_manager.broadcast(
        "state",
        {"state": request.app.state.orchestrator.state.model_dump(), "scenario": "city_loaded"},
    )

    return {
        "ok": True,
        "message": "City imported. The active simulator now uses the imported road graph.",
        "city": graph.model_dump(),
        "summary": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "buildings": len(graph.buildings),
            "infrastructure": len(graph.infrastructure),
            "hospitals": len(graph.hospitals),
            "attribution": graph.attribution or OSM_ATTRIBUTION,
        },
        "limitations": [
            "OpenStreetMap coverage is uneven; missing pipes, feeders, or sensors are not invented.",
            "Roads and buildings are imported now. Domain-specific power and water solvers can consume the preserved infrastructure assets.",
        ],
    }
