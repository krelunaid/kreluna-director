"""Chi pianifica: sicurezza e frasi certe alle regole, linguaggio incerto al modello IA."""

from __future__ import annotations

import httpx
from kreluna_shared.llm import plan_with_llm
from kreluna_shared.models import PlanResult
from kreluna_shared.planner import plan_deterministic

from app.config import AIProviderConfig, settings


async def plan_message(
    message: str,
    client: httpx.AsyncClient | None = None,
    *,
    provider: str | None = None,
    config: AIProviderConfig | None = None,
    history: list[dict[str, str]] | None = None,
) -> PlanResult:
    plan = plan_deterministic(message)
    resolved = config or settings.ai_provider_config(provider)
    # Le regole restano definitive per sicurezza e comandi completi. Quando hanno
    # ancora domande, invece, il modello può capire refusi e italiano parlato.
    if plan.source not in {"deterministic-unknown", "deterministic-ask"}:
        return plan
    if not resolved.configured:
        return PlanResult(
            ok=False,
            summary=(
                f"IA {resolved.label} non configurata: controlla modello e credenziali. "
                "Nessun lavoro è stato creato."
            ),
            source="llm-error",
            diagnostic={"code": "not_configured", "provider": resolved.provider},
        )
    if client is not None:
        from_model = await _ask(message, client, config=resolved, history=history)
    else:
        async with httpx.AsyncClient() as owned:
            from_model = await _ask(message, owned, config=resolved, history=history)
    return from_model or plan


async def _ask(
    message: str,
    client: httpx.AsyncClient,
    *,
    config: AIProviderConfig,
    history: list[dict[str, str]] | None = None,
) -> PlanResult | None:
    result = await plan_with_llm(
        message,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        client=client,
        timeout=45.0 if config.managed else 15.0,
        allow_anonymous=config.provider == "ollama",
        history=history,
    )
    if result is not None and result.source == "llm-error":
        result.diagnostic = {
            **(result.diagnostic or {}),
            "provider": config.provider,
            "model": config.model,
        }
    return result
