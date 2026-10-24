from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..tools.traffic import shortest_route

router = APIRouter(tags=["infrastructure"])


@router.get("/api/infrastructure/assets")
async def infrastructure_assets(request: Request) -> list[dict[str, Any]]:
    graph = request.app.state.graph
    return [asset.model_dump() for asset in graph.infrastructure]


@router.get("/api/infrastructure/diagnostics")
async def infrastructure_diagnostics(request: Request, domain: Literal["power", "water"] = "power") -> dict[str, Any]:
    graph = request.app.state.graph
    state = request.app.state.orchestrator.state
    if domain == "power":
        stations: list[dict[str, Any]] = []
        for sub in graph.substations:
            load = state.power_load_mw.get(sub.id, 0.0)
            utilization = load / sub.capacity_mw if sub.capacity_mw else 0.0
            feeders = []
            dark_signals: list[str] = []
            for fid in sub.feeders:
                served = [signal.id for signal in graph.signals if signal.feeder_id == fid]
                dark = [sid for sid in served if not state.signals_ok.get(sid, True)]
                dark_signals.extend(dark)
                feeders.append({"id": fid, "powered": state.powered.get(fid, False), "served_signals": served, "dark_signals": dark})
            failure = state.failed_assets.get(sub.id)
            if failure == "overload" or utilization > 1:
                status = "overloaded"
                cause = f"load {load:.1f} MW exceeds {sub.capacity_mw:.1f} MW capacity"
            elif failure or not any(item["powered"] for item in feeders):
                status = "offline"
                cause = failure or "all downstream feeders are offline"
            elif dark_signals:
                status = "degraded"
                cause = f"{len(dark_signals)} downstream signal(s) are dark"
            else:
                status = "healthy"
                cause = "no downstream failure detected"
            stations.append({
                "substation_id": sub.id,
                "node_id": sub.node_id,
                "status": status,
                "probable_cause": cause,
                "load_mw": round(load, 2),
                "capacity_mw": sub.capacity_mw,
                "utilization": round(utilization, 3),
                "feeders": feeders,
                "dark_signals": dark_signals,
                "recommended_actions": [item for item in [
                    "inspect upstream line and breaker" if status in {"offline", "overloaded"} else "continue monitoring",
                    "reroute critical loads before dispatching repair crews" if dark_signals else None,
                ] if item],
            })
        probable = sorted(stations, key=lambda item: (item["status"] == "healthy", -item["utilization"]))
        return {
            "domain": "power",
            "answer": "Power diagnostics rank the most likely failing station from load, feeder, and downstream signal evidence.",
            "probable_station": probable[0] if probable and probable[0]["status"] != "healthy" else None,
            "stations": stations,
        }

    assets = [asset for asset in graph.infrastructure if asset.kind in {"pipeline", "waterway", "water_works", "wastewater_plant"}]
    details = []
    for asset in assets:
        pressure = state.water_pressure_kpa.get(asset.id)
        failure = state.water_failures.get(asset.id) or state.failed_assets.get(asset.id)
        status = "failed" if failure else "healthy" if pressure is not None else "unknown"
        details.append({
            "asset_id": asset.id,
            "kind": asset.kind,
            "name": asset.name,
            "status": status,
            "probable_cause": failure or (f"pressure {pressure:.0f} kPa" if pressure is not None else "no pressure telemetry"),
            "pressure_kpa": pressure,
            "recommended_actions": ["isolate the affected segment", "dispatch water maintenance crew"] if failure else ["attach pressure telemetry"],
        })
    return {
        "domain": "water",
        "answer": "Water diagnostics identify failed or low-pressure mapped assets; unmapped utility data is reported as unknown rather than invented.",
        "assets": details,
        "failed_assets": [item for item in details if item["status"] == "failed"],
    }


@router.get("/api/hospitals")
async def hospitals(request: Request) -> list[dict[str, Any]]:
    graph = request.app.state.graph
    return [hospital.model_dump() for hospital in graph.hospitals]


@router.get("/api/hospitals/{hospital_id}")
async def hospital_detail(hospital_id: str, request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    hospital = next((item for item in graph.hospitals if item.id == hospital_id), None)
    if not hospital:
        raise HTTPException(status_code=404, detail=f"Hospital not found: {hospital_id}")
    state = request.app.state.orchestrator.state
    route = shortest_route(graph, state, "DEPOT", hospital.node_id) if any(node.id == "DEPOT" for node in graph.nodes) else None
    return {**hospital.model_dump(), "reachable_from_depot": route["reachable"] if route else None, "route": route}


class VehicleRouteRequest(BaseModel):
    vehicle_type: Literal["firetruck", "police", "ambulance"]
    origin: str = "DEPOT"
    destination_node: str | None = None
    hospital_id: str | None = None
    incident_edge_id: str | None = None


@router.post("/api/routes/vehicles")
async def vehicle_route(body: VehicleRouteRequest, request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
    state = request.app.state.orchestrator.state
    destination = body.destination_node
    if body.hospital_id:
        hospital = next((item for item in graph.hospitals if item.id == body.hospital_id), None)
        if not hospital:
            raise HTTPException(status_code=404, detail=f"Hospital not found: {body.hospital_id}")
        destination = hospital.node_id
    if not destination:
        raise HTTPException(status_code=422, detail="destination_node or hospital_id is required")
    known_nodes = {node.id for node in graph.nodes}
    if body.origin not in known_nodes or destination not in known_nodes:
        raise HTTPException(status_code=422, detail="origin and destination must be nodes in the active city")
    route = shortest_route(graph, state, body.origin, destination)
    if not route["reachable"]:
        answer = f"No safe route is currently available for the {body.vehicle_type}."
    else:
        answer = f"Recommended {body.vehicle_type} route uses {len(route['edges'])} edge(s) and takes about {route['travel_s']:.0f} seconds."
    return {
        "ok": True,
        "vehicle_type": body.vehicle_type,
        "origin": body.origin,
        "destination": destination,
        "incident_edge_id": body.incident_edge_id,
        "answer": answer,
        "route": route,
        "avoid_edges": sorted(set(state.flooded_edges) | {edge_id for edge_id, closed in state.closed_edges.items() if closed}),
    }
