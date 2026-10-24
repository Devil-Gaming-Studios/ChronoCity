from __future__ import annotations

from fastapi import FastAPI

from .agents.orchestrator import Orchestrator
from .agents.workflow import Workflow
from .models import CityGraph


def install_city(app: FastAPI, graph: CityGraph) -> None:
    """Install a city graph and reset runtime state bound to the old graph."""
    app.state.graph = graph
    audit = getattr(app.state, "audit", None)
    if audit:
        import uuid
        audit.runtime_id = uuid.uuid4().hex
        audit.city = graph.name
        audit.record("city_installed", {"city": graph.model_dump(mode="json")}, summary="City runtime started; older plans are history only")
    app.state.orchestrator = Orchestrator(graph, audit=audit.record if audit else None)
    app.state.workflow = Workflow(app.state.orchestrator, graph)
    app.state.last_what_if = None
