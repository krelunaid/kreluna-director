"""Chi pianifica: ogni richiesta normale va all'IA; la policy locale resta l'autorità."""

from __future__ import annotations

import httpx
from kreluna_shared.llm import plan_with_llm
from kreluna_shared.models import PlanResult
from kreluna_shared.planner import plan_deterministic

from app.config import AIProviderConfig, settings


def _reconcile_invoice_facts(local: PlanResult, model: PlanResult) -> PlanResult:
    """Conserva i dati fiscali scritti dall'utente senza nascondere guasti IA.

    Il modello continua a interpretare ogni richiesta normale. Per una fattura
    completa, pero', cliente/importo/descrizione/IVA estratti dal testo locale
    sono l'autorita': non ha senso chiedere di nuovo un importo gia' presente.
    Se il provider e' davvero guasto, l'errore resta esplicito e non si crea
    alcun task.
    """

    if model.source == "llm-error" or model.denied:
        return model

    def is_invoice(task) -> bool:
        return task.capability == "invoice_prepare_demo" or (
            task.capability == "portal_open"
            and task.args.get("portal") == "fatture-webdesk"
            and bool(task.args.get("invoice"))
        )

    local_invoice = next((task for task in local.tasks if is_invoice(task)), None)
    if local.ok and local_invoice is not None:
        model_invoice = next((task for task in model.tasks if is_invoice(task)), None)
        summary = model.summary if model.ok and model_invoice is not None else local.summary
        return local.model_copy(
            update={
                "summary": summary,
                "source": "llm-grounded",
                "diagnostic": {"code": "invoice_facts_grounded"},
            }
        )

    pending = local.pending or {}
    if (
        not model.ok
        and model.source == "llm-ask"
        and pending.get("capability") == "invoice_prepare_demo"
    ):
        return model.model_copy(update={"pending": pending})
    return model


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
    # I blocchi di sicurezza e il fermo d'emergenza non raggiungono mai il modello.
    if plan.denied or plan.source == "deterministic-kill":
        return plan
    if not resolved.configured:
        # La demo e le installazioni senza provider restano operative per i
        # comandi locali che il planner ha già compreso senza inventare dati.
        # Una frase sconosciuta continua invece a fermarsi esplicitamente: non
        # fingiamo che l'IA abbia capito e non creiamo task ambigui.
        if plan.ok or plan.pending or plan.source == "deterministic-help":
            return plan.model_copy(
                update={
                    "source": "deterministic-offline",
                    "diagnostic": {
                        "code": "local_planner",
                        "provider": resolved.provider,
                    },
                }
            )
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
    if from_model is not None:
        return _reconcile_invoice_facts(plan, from_model)
    return PlanResult(
        ok=False,
        summary="IA non disponibile: configurazione incompleta. Nessun lavoro è stato creato.",
        source="llm-error",
        diagnostic={"code": "not_configured", "provider": resolved.provider},
    )


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
