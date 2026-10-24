from __future__ import annotations

import pytest

from app.city.build_city import build_demo_city
from app.sim.scenarios import combined_state, flood_state, trip_state
from app.sim.state import initial_state


@pytest.fixture(autouse=True)
def isolated_audit_database(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "audit_db_path", str(tmp_path / "audit.sqlite3"))


@pytest.fixture(scope="session")
def graph():
    return build_demo_city()


@pytest.fixture
def healthy(graph):
    return initial_state(graph)


@pytest.fixture
def flooded(graph):
    return flood_state(graph)


@pytest.fixture
def tripped(graph):
    return trip_state(graph)


@pytest.fixture
def combined(graph):
    return combined_state(graph)
