from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .simulations import SimulationRequest, run_simulation

router = APIRouter(prefix="/api/commands", tags=["commands"])


class CommandRequest(BaseModel):
    text: str
    start_from: str = "healthy"
    selected_entity_id: str | None = None
    selected_entity_type: str | None = None


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def parse_command(body: CommandRequest) -> tuple[dict[str, Any], SimulationRequest | None]:
    text = body.text.strip()
    lowered = text.lower()
    if not text:
        return {"ok": False, "answer": "Type a command such as 'rain 120 mm' or 'trip substation S2'.", "suggestions": ["rain 120 mm", "set substation S2 load to 45 MW", "break pipe ASSET_ID"]}, None

    hazards: list[dict[str, Any]] = []
    parsed: dict[str, Any] = {"text": text}
    rain = _number(r"(\d+(?:\.\d+)?)\s*mm", text)
    if "rain" in lowered or "rainfall" in lowered:
        if rain is None:
            return {"ok": False, "answer": "I need the rainfall amount, for example: rain 120 mm.", "suggestions": ["rain 120 mm"]}, None
        duration = _number(r"(?:over|for)\s+(\d+(?:\.\d+)?)\s*(?:min|minutes)", text) or 30.0
        hazards.append({"type": "rain", "rain_mm": rain, "duration_min": duration, "label": text})
        parsed.update({"intent": "rain", "rain_mm": rain, "duration_min": duration})
    else:
        station_match = re.search(r"(?:substation|station)\s+([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        load = _number(r"(\d+(?:\.\d+)?)\s*(?:mw|megawatts?)", text)
        if ("trip" in lowered or "outage" in lowered or "offline" in lowered) and station_match:
            hazards.append({"type": "power_outage", "substation_id": station_match.group(1), "label": text})
            parsed.update({"intent": "power_outage", "substation_id": station_match.group(1)})
        elif ("power" in lowered or "load" in lowered) and station_match and load is not None:
            hazards.append({"type": "power_overload", "substation_id": station_match.group(1), "load_mw": load, "label": text})
            parsed.update({"intent": "power_overload", "substation_id": station_match.group(1), "load_mw": load})
        elif ("wire" in lowered or "power line" in lowered) and ("break" in lowered or "cut" in lowered or "disable" in lowered):
            asset = re.search(r"(?:wire|power line|line)\s+([A-Za-z0-9_.:-]+)", text, re.IGNORECASE)
            asset_id = asset.group(1) if asset else body.selected_entity_id
            if not asset_id:
                return {"ok": False, "answer": "Select a power line in the 3D map or include its asset ID.", "suggestions": ["break wire ASSET_ID"]}, None
            hazards.append({"type": "power_wire_break", "asset_id": asset_id, "label": text})
            parsed.update({"intent": "power_wire_break", "asset_id": asset_id})
        elif ("pipe" in lowered or "pipeline" in lowered or "water" in lowered) and ("break" in lowered or "cut" in lowered or "disable" in lowered):
            asset = re.search(r"(?:pipe|pipeline|water)\s+([A-Za-z0-9_.:-]+)", text, re.IGNORECASE)
            asset_id = asset.group(1) if asset else body.selected_entity_id
            if not asset_id:
                return {"ok": False, "answer": "Select a water asset in the 3D map or include its asset ID.", "suggestions": ["break pipe ASSET_ID"]}, None
            hazards.append({"type": "water_pipe_break", "asset_id": asset_id, "label": text})
            parsed.update({"intent": "water_pipe_break", "asset_id": asset_id})
        elif "disable" in lowered or "close" in lowered:
            entity_id = body.selected_entity_id or (re.search(r"(?:edge|road)\s+([A-Za-z0-9_.:-]+)", text, re.IGNORECASE) or [None, None])[1]
            entity_type = body.selected_entity_type or "edge"
            if not entity_id:
                return {"ok": False, "answer": "Select a map feature first, or say 'disable edge EDGE_ID'.", "suggestions": ["disable selected feature", "disable edge EDGE_ID"]}, None
            if entity_type == "substation":
                hazards.append({"type": "power_outage", "substation_id": entity_id, "label": text})
                parsed.update({"intent": "power_outage", "substation_id": entity_id})
            elif entity_type == "power_line":
                hazards.append({"type": "power_wire_break", "asset_id": entity_id, "label": text})
                parsed.update({"intent": "power_wire_break", "asset_id": entity_id})
            elif entity_type in {"pipeline", "waterway", "water_works", "wastewater_plant"}:
                hazards.append({"type": "water_pipe_break", "asset_id": entity_id, "label": text})
                parsed.update({"intent": "water_pipe_break", "asset_id": entity_id})
            else:
                hazards.append({"type": "close_edge", "edge_id": entity_id, "label": text})
                parsed.update({"intent": "close_edge", "edge_id": entity_id})
        else:
            return {"ok": False, "answer": "I could not map that command to a safe simulation input.", "suggestions": ["rain 120 mm", "trip substation S2", "set substation S2 load to 45 MW", "disable selected feature"]}, None

    return parsed, SimulationRequest(label=text, start_from="current" if body.start_from == "current" else "healthy", hazards=hazards)


@router.post("/run")
async def run_command(body: CommandRequest, request: Request) -> dict[str, Any]:
    parsed, simulation = parse_command(body)
    if simulation is None:
        return parsed
    response = await run_simulation(simulation, request)
    response["parsed"] = parsed
    return response
