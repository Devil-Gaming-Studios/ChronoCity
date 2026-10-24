import pytest

from app.city import osm


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "elements": [
                {
                    "type": "way",
                    "id": 10,
                    "tags": {"highway": "residential", "name": "Main Street", "lanes": "2"},
                    "geometry": [
                        {"lat": 40.0, "lon": -74.0},
                        {"lat": 40.0005, "lon": -74.0},
                    ],
                },
                {
                    "type": "way",
                    "id": 11,
                    "tags": {"building": "yes", "building:levels": "3"},
                    "geometry": [
                        {"lat": 40.0001, "lon": -74.0002},
                        {"lat": 40.0001, "lon": -74.0001},
                        {"lat": 40.0002, "lon": -74.0001},
                        {"lat": 40.0002, "lon": -74.0002},
                    ],
                },
                {
                    "type": "way",
                    "id": 12,
                    "tags": {"power": "line"},
                    "geometry": [
                        {"lat": 40.0, "lon": -74.0},
                        {"lat": 40.0005, "lon": -74.0},
                    ],
                },
            ]
        }


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs):
        return FakeResponse()


@pytest.mark.asyncio
async def test_import_osm_builds_graph_and_3d_assets(monkeypatch):
    monkeypatch.setattr(osm.httpx, "AsyncClient", FakeClient)

    graph = await osm.import_osm_bbox(39.99, -74.01, 40.01, -73.99, name="Test OSM")

    assert graph.source == "osm"
    assert graph.name == "Test OSM"
    assert len(graph.edges) == 1
    assert graph.edges[0].name == "Main Street"
    assert len(graph.buildings) == 1
    assert graph.buildings[0].levels == 3
    assert graph.infrastructure[0].kind == "power_line"
