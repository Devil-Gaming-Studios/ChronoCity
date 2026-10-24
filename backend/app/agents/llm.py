from __future__ import annotations

import json
from typing import Any

from ..config import settings


class LLMClient:
    """Thin, mode-switchable LLM access.

    - scripted: deterministic, offline, zero network. Returns canned-but-plausible
      structured outputs so the whole demo runs with the network off.
    - ollama: local model via HTTP.
    - gemini / claude: live APIs (needs keys + google-adk / litellm installed).

    Every call is counted against a per-incident budget so we can prove
    'LLM calls scale with incidents, not data'.
    """

    def __init__(self) -> None:
        self.mode = settings.llm_mode
        self.budget = settings.llm_call_budget
        self.calls_used = 0
        self._call_log: list[dict[str, Any]] = []

    def reset_budget(self) -> None:
        self.calls_used = 0

    def budget_ok(self) -> bool:
        return self.calls_used < self.budget

    def _record(self, agent: str, kind: str, ok: bool = True) -> None:
        self.calls_used += 1
        self._call_log.append({"agent": agent, "kind": kind, "ok": ok})

    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "calls_used": self.calls_used,
            "budget": self.budget,
            "log": list(self._call_log),
        }

    async def complete(self, agent: str, prompt: str, *, schema_hint: str = "") -> str:
        """Return raw model text for a prompt. In scripted mode this is canned."""
        if not self.budget_ok():
            self._record(agent, "budget_exhausted", ok=False)
            return json.dumps({"error": "budget_exhausted"})

        self._record(agent, "complete")
        if self.mode == "scripted":
            return _scripted(agent, prompt)
        if self.mode == "ollama":
            return await self._ollama(prompt)
        if self.mode == "gemini":
            return await self._gemini(prompt)
        if self.mode == "claude":
            return await self._claude(prompt)
        return _scripted(agent, prompt)

    async def _ollama(self, prompt: str) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={"model": settings.llm_model, "prompt": prompt, "stream": False},
                )
                r.raise_for_status()
                return r.json().get("response", "")
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"ollama_failed: {e}"})

    async def _gemini(self, prompt: str) -> str:
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(settings.llm_model)
            resp = await model.generate_content_async(prompt)
            return resp.text or ""
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"gemini_failed: {e}"})

    async def _claude(self, prompt: str) -> str:
        try:
            import litellm  # type: ignore

            resp = await litellm.acompletion(
                model="claude-3-5-sonnet-20241022",
                messages=[{"role": "user", "content": prompt}],
                api_key=settings.anthropic_api_key or None,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"claude_failed: {e}"})


def _scripted(agent: str, prompt: str) -> str:
    """Deterministic offline responses keyed on the agent role.

    These mirror what a real model would emit, so the pipeline logic is fully
    exercised without any network. The Negotiator/Critic decisions themselves
    are computed in code (deterministic), so these are only used for the
    natural-language summaries.
    """
    if "power" in agent.lower():
        return "Backfeed the dark southern feeders from substation S1 via a temporary tie, shedding non-critical load."
    if "traffic" in agent.lower():
        return "Close the flooded underpass edge and reroute traffic onto the J5-J7 corridor to keep the hospital approach open."
    if "emergency" in agent.lower():
        return "Dispatch ambulance A1 via the northern corridor to H1, avoiding the flooded underpass and dark junctions."
    if "negotiator" in agent.lower():
        return "Resolve the shared-ambulance conflict by granting Emergency ownership; Traffic yields the corridor and Power keeps the northern feed energized."
    if "critic" in agent.lower() or "revis" in agent.lower():
        return "Simulation shows the hospital approach stays open and ambulance ETA improves; plan verified."
    return "Ack."


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


__all__ = ["LLMClient", "get_llm"]
