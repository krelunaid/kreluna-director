"""Chi pianifica: prima le regole dello studio, poi il modello IA se le regole non capiscono."""

from __future__ import annotations

import httpx
from kreluna_shared.llm import plan_with_llm
from kreluna_shared.models import PlanResult
from kreluna_shared.planner import plan_deterministic

from app.config import settings


async def plan_message(message: str, client: httpx.AsyncClient | None = None) -> PlanResult:
    plan = plan_deterministic(message)
    if plan.source != "deterministic-unknown" or not settings.llm_ready:
        return plan
    if client is not None:
        from_model = await _ask(message, client)
    else:
        async with httpx.AsyncClient() as owned:
            from_model = await _ask(message, owned)
    return from_model or plan


async def _ask(message: str, client: httpx.AsyncClient) -> PlanResult | None:
    return await plan_with_llm(
        message,
        base_url=settings.kreluna_llm_base_url,
        api_key=settings.kreluna_llm_api_key,
        model=settings.kreluna_llm_model,
        client=client,
    )
