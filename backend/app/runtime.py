from __future__ import annotations

from fastapi import FastAPI

from .agents.orchestrator import Orchestrator
from .agents.workflow import Workflow
from .models import CityGraph


def install_city(app: FastAPI, graph: CityGraph) -> None:
    """Install a city graph and reset runtime state bound to the old graph."""
    app.state.graph = graph
    app.state.orchestrator = Orchestrator(graph)
    app.state.workflow = Workflow(app.state.orchestrator, graph)
    app.state.last_what_if = None
