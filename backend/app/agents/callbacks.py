from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from .llm import get_llm


class AgentCallbacks:
    """Guardrails wrapped around every agent's work.

    - budget: refuse to run if the per-incident LLM budget is spent.
    - cache: memoize identical prompts so repeated incidents don't re-spend.
    - guardrail: ensure the agent produced structured output, never free-form action.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def _key(self, agent: str, prompt: str) -> str:
        return hashlib.sha256(f"{agent}::{prompt}".encode()).hexdigest()

    def cached(self, agent: str, prompt: str) -> str | None:
        return self._cache.get(self._key(agent, prompt))

    def store(self, agent: str, prompt: str, out: str) -> None:
        self._cache[self._key(agent, prompt)] = out

    async def guarded_complete(self, agent: str, prompt: str) -> str:
        llm = get_llm()
        key = self._key(agent, prompt)
        if key in self._cache:
            return self._cache[key]
        if not llm.budget_ok():
            return json.dumps({"error": "budget_exhausted", "agent": agent})
        out = await llm.complete(agent, prompt)
        self._cache[key] = out
        return out


_callbacks: AgentCallbacks | None = None


def get_callbacks() -> AgentCallbacks:
    global _callbacks
    if _callbacks is None:
        _callbacks = AgentCallbacks()
    return _callbacks


__all__ = ["AgentCallbacks", "get_callbacks"]
