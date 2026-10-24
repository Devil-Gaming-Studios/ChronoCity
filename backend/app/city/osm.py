from __future__ import annotations

import math
from typing import Any

import httpx

from ..models import (
    Building,
    CityGraph,
    Edge,
    Feeder,
    Hospital,
    HospitalDepartment,
    InfrastructureAsset,
    Node,
    Substation,
    Underpass,
)


OSM_ATTRIBUTION = "© OpenStreetMap contributors · ODbL"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Footways and similar ways are useful map context, but are not vehicle routes in
# this first importer. Domain-specific pedestrian simulation can be added later.
DRIVABLE_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}
DEFAULT_SPEED_KPH = {
    "motorway": 100.0,
    "trunk": 80.0,
    "primary": 60.0,
    "secondary": 50.0,
    "tertiary": 40.0,
    "residential": 30.0,
    "living_street": 20.0,
    "service": 15.0,
    "unclassified": 30.0,
}


def _number(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        token = str(value).replace(",", ".").split()[0]
        return float(token)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return max(1, int(float(str(value).split()[0])))
    except (TypeError, ValueError):
        return default


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _project(lat: float, lon: float, center_lat: float, center_lon: float) -> tuple[float, float]:
    """Project WGS84 to local hundred-metre coordinates for the existing renderer."""
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = meters_per_degree_lat * math.cos(math.radians(center_lat))
    return (
        (lon - center_lon) * meters_per_degree_lon / 100.0,
        (lat - center_lat) * meters_per_degree_lat / 100.0,
    )


def _tags(element: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in (element.get("tags") or {}).items()}


def _element_point(element: dict[str, Any]) -> tuple[float, float] | None:
    if isinstance(element.get("lat"), (int, float)) and isinstance(element.get("lon"), (int, float)):
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if isinstance(center.get("lat"), (int, float)) and isinstance(center.get("lon"), (int, float)):
        return float(center["lat"]), float(center["lon"])
    geometry = element.get("geometry") or []
    if geometry:
        point = geometry[len(geometry) // 2]
        if isinstance(point.get("lat"), (int, float)) and isinstance(point.get("lon"), (int, float)):
            return float(point["lat"]), float(point["lon"])
    return None


def _node_key(lat: float, lon: float) -> str:
    return f"{lat:.7f}:{lon:.7f}"


def _node_id(key: str) -> str:
    return "OSM_N_" + key.replace("-", "m").replace(":", "_").replace(".", "d")


def _height(tags: dict[str, str]) -> tuple[float, int | None]:
    levels = _int(tags.get("building:levels"), 0) if tags.get("building:levels") else 0
    if tags.get("height"):
        return max(2.5, _number(tags["height"], 8.0)), levels or None
    if levels:
        return max(2.5, levels * 3.2), levels
    return 8.0, None


def _query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:35];
(
  way[\"highway\"]({bbox});
  way[\"building\"]({bbox});
  way[\"power\"~\"^(line|minor_line)$\"]({bbox});
  way[\"waterway\"]({bbox});
  way[\"man_made\"~\"^(pipeline|water_works|wastewater_plant)$\"]({bbox});
  nwr[\"amenity\"=\"hospital\"]({bbox});
  nwr[\"power\"=\"substation\"]({bbox});
);
out body center geom;"""


async def import_osm_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    name: str = "OpenStreetMap area",
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = "ChronoTwin/0.1 (city digital twin prototype)",
) -> CityGraph:
    """Fetch an OSM bbox and turn roads/buildings/assets into a CityGraph.

    The importer intentionally keeps geometry local and lightweight: roads become
    graph edges, buildings become extrudable footprints, and power/water features
    are preserved as infrastructure assets for domain simulators.
    """
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("Invalid bbox: expected south < north and west < east in WGS84 degrees")
    if north - south > 0.12 or east - west > 0.12:
        raise ValueError("bbox is too large; limit imports to roughly a 13 km by 13 km area")

    async with httpx.AsyncClient(timeout=55.0, headers={"User-Agent": user_agent}) as client:
        response = await client.post(overpass_url, data={"data": _query(south, west, north, east)})
        response.raise_for_status()
        payload = response.json()

    elements = payload.get("elements") or []
    center_lat = (south + north) / 2
    center_lon = (west + east) / 2
    nodes_by_key: dict[str, dict[str, Any]] = {}
    edges: list[Edge] = []
    underpasses: list[Underpass] = []
    buildings: list[Building] = []
    infrastructure: list[InfrastructureAsset] = []
    hospitals: list[Hospital] = []
    substations: list[Substation] = []
    feeders: list[Feeder] = []
    road_ways = 0
    building_ways = 0

    def ensure_node(lat: float, lon: float, tags: dict[str, str] | None = None) -> str:
        key = _node_key(lat, lon)
        if key not in nodes_by_key:
            x, y = _project(lat, lon, center_lat, center_lon)
            nodes_by_key[key] = {
                "id": _node_id(key),
                "lat": lat,
                "lon": lon,
                "x": x,
                "y": y,
                "tags": tags or {},
            }
        elif tags:
            nodes_by_key[key]["tags"].update(tags)
        return nodes_by_key[key]["id"]

    for element in elements:
        kind = element.get("type")
        tags = _tags(element)
        geometry = element.get("geometry") or []
        if kind == "way" and tags.get("highway") in DRIVABLE_HIGHWAYS and len(geometry) >= 2:
            road_ways += 1
            points = [(float(p["lat"]), float(p["lon"])) for p in geometry]
            highway = tags.get("highway", "residential")
            speed = _number(tags.get("maxspeed"), DEFAULT_SPEED_KPH.get(highway, 30.0))
            lanes = _int(tags.get("lanes"), 1)
            way_id = str(element.get("id", "way"))
            underpass = tags.get("tunnel") in {"yes", "true", "1"} or tags.get("covered") in {"yes", "true", "1"}
            for index, (a, b) in enumerate(zip(points, points[1:])):
                length = _haversine_m(a, b)
                if length < 1.0:
                    continue
                src = ensure_node(*a)
                dst = ensure_node(*b)
                edge_id = f"OSM_E_{way_id}_{index}"
                edges.append(
                    Edge(
                        id=edge_id,
                        src=src,
                        dst=dst,
                        length_m=round(length, 2),
                        lanes=lanes,
                        free_flow_kph=max(5.0, speed),
                        kind="underpass" if underpass else "road",
                        name=tags.get("name", ""),
                        osm_id=way_id,
                        tags=tags,
                    )
                )
                if underpass and index == 0:
                    underpasses.append(Underpass(id=f"U_{way_id}", edge_id=edge_id, name=tags.get("name", "OSM underpass")))
            continue

        if kind == "way" and "building" in tags and len(geometry) >= 3:
            building_ways += 1
            footprint = [_project(float(p["lat"]), float(p["lon"]), center_lat, center_lon) for p in geometry]
            point = _element_point(element)
            height_m, levels = _height(tags)
            buildings.append(
                Building(
                    id=f"OSM_B_{element.get('id', len(buildings))}",
                    name=tags.get("name", ""),
                    kind=tags.get("building", "building"),
                    footprint=footprint,
                    height_m=height_m,
                    levels=levels,
                    lat=point[0] if point else None,
                    lon=point[1] if point else None,
                    osm_id=str(element.get("id", "")),
                    tags=tags,
                )
            )
            continue

        if kind == "way" and (
            tags.get("waterway")
            or tags.get("power") in {"line", "minor_line"}
            or tags.get("man_made") in {"pipeline", "water_works", "wastewater_plant"}
        ) and len(geometry) >= 2:
            path = [_project(float(p["lat"]), float(p["lon"]), center_lat, center_lon) for p in geometry]
            if tags.get("waterway"):
                asset_kind = "waterway"
            elif tags.get("power"):
                asset_kind = "power_line"
            else:
                asset_kind = str(tags.get("man_made"))
            infrastructure.append(
                InfrastructureAsset(
                    id=f"OSM_A_{element.get('id', len(infrastructure))}",
                    kind=asset_kind,
                    geometry=path,
                    name=tags.get("name", ""),
                    osm_id=str(element.get("id", "")),
                    tags=tags,
                )
            )

    nodes: list[Node] = [
        Node(
            id=data["id"],
            kind="junction",
            x=data["x"],
            y=data["y"],
            zone="OSM",
            name=data["tags"].get("name", data["id"]),
            lat=data["lat"],
            lon=data["lon"],
            osm_id=data["id"],
            tags=data["tags"],
        )
        for data in nodes_by_key.values()
    ]

    def add_asset_node(element: dict[str, Any], node_kind: str, fallback_name: str) -> str | None:
        point = _element_point(element)
        if not point:
            return None
        lat, lon = point
        x, y = _project(lat, lon, center_lat, center_lon)
        node_id = f"OSM_{node_kind.upper()}_{element.get('type', 'x')}_{element.get('id', len(nodes))}"
        if any(n.id == node_id for n in nodes):
            return node_id
        tags = _tags(element)
        nodes.append(Node(id=node_id, kind=node_kind, x=x, y=y, zone="OSM", name=tags.get("name", fallback_name), lat=lat, lon=lon, osm_id=str(element.get("id", "")), tags=tags))
        if nodes_by_key:
            nearest = min(nodes_by_key.values(), key=lambda n: _haversine_m((lat, lon), (n["lat"], n["lon"])))
            nearest_point = (nearest["lat"], nearest["lon"])
            distance = _haversine_m((lat, lon), nearest_point)
            if distance <= 500:
                edges.append(Edge(id=f"OSM_CONNECT_{node_id}", src=node_id, dst=nearest["id"], length_m=round(distance, 2), lanes=1, free_flow_kph=20.0, name="asset connector", tags={"source": "chronotwin"}))
        return node_id

    for element in elements:
        tags = _tags(element)
        if tags.get("amenity") == "hospital":
            node_id = add_asset_node(element, "hospital", "Hospital")
            if node_id:
                hospital_id = f"H_{element.get('id', len(hospitals))}"
                hospitals.append(
                    Hospital(
                        id=hospital_id,
                        node_id=node_id,
                        name=tags.get("name", "Hospital"),
                        departments=[
                            HospitalDepartment(id=f"{hospital_id}-ED", name="Emergency", total_beds=20, available_beds=10),
                            HospitalDepartment(id=f"{hospital_id}-ICU", name="ICU", total_beds=8, available_beds=3),
                        ],
                    )
                )
        if tags.get("power") == "substation":
            node_id = add_asset_node(element, "substation", "Substation")
            if node_id:
                sid = f"S_{element.get('id', len(substations))}"
                fid = f"F_{element.get('id', len(feeders))}"
                substations.append(Substation(id=sid, node_id=node_id, feeders=[fid], capacity_mw=40.0))
                feeders.append(Feeder(id=fid, substation_id=sid, serves=[]))

    return CityGraph(
        nodes=nodes,
        edges=edges,
        substations=substations,
        feeders=feeders,
        signals=[],
        hospitals=hospitals,
        underpasses=underpasses,
        buildings=buildings,
        infrastructure=infrastructure,
        source="osm",
        source_ref=f"bbox:{south},{west},{north},{east}",
        name=name,
        bounds={"south": south, "west": west, "north": north, "east": east},
        attribution=OSM_ATTRIBUTION,
    )


__all__ = ["DEFAULT_OVERPASS_URL", "OSM_ATTRIBUTION", "import_osm_bbox"]
