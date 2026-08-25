from __future__ import annotations

import hashlib
import re
import time
from binascii import Error as BinasciiError
from dataclasses import replace
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from kreluna_shared.crypto import decrypt_secret_text, encrypt_secret_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AI_PROVIDERS, AIProviderConfig, settings
from app.models import AIProviderCredential, AISelection, utcnow

_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
HEALTH_CACHE_SECONDS = 30
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}")


async def selected_provider(session: AsyncSession, tenant_id: str) -> str:
    row = await session.get(AISelection, tenant_id)
    return row.provider if row is not None else settings.selected_ai_provider


async def save_selected_provider(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    actor_id: str,
) -> str:
    cleaned = provider.strip().lower()
    if cleaned not in AI_PROVIDERS:
        raise ValueError("Provider IA sconosciuto")
    row = await session.get(AISelection, tenant_id)
    if row is None:
        row = AISelection(tenant_id=tenant_id, provider=cleaned, updated_by=actor_id)
        session.add(row)
    else:
        row.provider = cleaned
        row.updated_by = actor_id
        row.updated_at = utcnow()
    await session.flush()
    return cleaned


def _credential_context(tenant_id: str, provider: str) -> str:
    return f"ai-provider:{tenant_id}:{provider}:api-key"


async def provider_config(
    session: AsyncSession,
    tenant_id: str,
    provider: str | None = None,
) -> AIProviderConfig:
    """Resolve one provider without ever returning its stored secret to the UI."""

    selected = (provider or await selected_provider(session, tenant_id)).strip().lower()
    base = settings.ai_provider_config(selected)
    if base.managed:
        return base
    row = await session.get(
        AIProviderCredential,
        {"tenant_id": tenant_id, "provider": selected},
    )
    if row is None:
        return base
    api_key = base.api_key
    credential_error = ""
    if row.api_key_ciphertext:
        try:
            api_key = decrypt_secret_text(
                settings.director_credential_key,
                row.api_key_ciphertext,
                context=_credential_context(tenant_id, selected),
            ).strip()
        except (BinasciiError, InvalidTag, UnicodeDecodeError, ValueError):
            api_key = ""
            credential_error = "stored_key_unreadable"
    return replace(
        base,
        api_key=api_key,
        model=row.model.strip() or base.model,
        credential_error=credential_error,
    )


def _clean_model(value: str, *, fallback: str) -> str:
    model = value.strip() or fallback.strip()
    if not MODEL_PATTERN.fullmatch(model):
        raise ValueError("Nome modello non valido")
    return model


async def save_provider_configuration(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    model: str,
    api_key: str | None,
    actor_id: str,
) -> AIProviderConfig:
    """Encrypt a tenant API key and persist only its ciphertext."""

    cleaned = provider.strip().lower()
    if cleaned not in AI_PROVIDERS:
        raise ValueError("Provider IA sconosciuto")
    base = settings.ai_provider_config(cleaned)
    if base.managed:
        raise ValueError("L'IA Kreluna è gestita dalla licenza e non richiede una chiave API")
    clean_model = _clean_model(model, fallback=base.model)
    row = await session.get(
        AIProviderCredential,
        {"tenant_id": tenant_id, "provider": cleaned},
    )
    if row is None:
        row = AIProviderCredential(
            tenant_id=tenant_id,
            provider=cleaned,
            model=clean_model,
            api_key_ciphertext="",
            updated_by=actor_id,
        )
        session.add(row)
    else:
        row.model = clean_model
        row.updated_by = actor_id
        row.updated_at = utcnow()

    supplied_key = api_key.strip() if api_key is not None else ""
    if cleaned == "ollama":
        row.api_key_ciphertext = ""
    elif supplied_key:
        if len(supplied_key) < 20 or len(supplied_key) > 512:
            raise ValueError("La chiave API non ha una lunghezza valida")
        row.api_key_ciphertext = encrypt_secret_text(
            settings.director_credential_key,
            supplied_key,
            context=_credential_context(tenant_id, cleaned),
        )
    await session.flush()
    _HEALTH_CACHE.clear()
    return await provider_config(session, tenant_id, cleaned)


def _not_configured(config: AIProviderConfig) -> dict[str, Any]:
    if config.credential_error:
        return {
            "provider": config.provider,
            "label": config.label,
            "model": config.model,
            "configured": False,
            "connected": False,
            "status": "credential_error",
            "detail": "La chiave salvata non è leggibile: inseriscila nuovamente",
            "managed": config.managed,
            "configurable": config.configurable,
        }
    missing: list[str] = []
    if not config.model:
        missing.append("modello")
    if config.provider != "ollama" and not config.api_key:
        missing.append("licenza Kreluna" if config.managed else "chiave API")
    if not config.base_url:
        missing.append("indirizzo")
    return {
        "provider": config.provider,
        "label": config.label,
        "model": config.model,
        "configured": False,
        "connected": False,
        "status": "not_configured",
        "detail": "Configurazione incompleta: " + ", ".join(missing),
        "managed": config.managed,
        "configurable": config.configurable,
    }


def _health_url(config: AIProviderConfig) -> str:
    base = config.base_url.rstrip("/")
    if config.provider == "ollama":
        base = base.removesuffix("/v1")
        return base + "/api/tags"
    return base + "/models"


def _model_ids(config: AIProviderConfig, payload: dict[str, Any]) -> set[str]:
    if config.provider == "ollama":
        rows = payload.get("models") or []
        return {
            str(row.get("name") or row.get("model") or "")
            for row in rows
            if isinstance(row, dict)
        }
    rows = payload.get("data") or []
    return {str(row.get("id") or "") for row in rows if isinstance(row, dict)}


def _cache_key(config: AIProviderConfig) -> str:
    key_fingerprint = hashlib.sha256(config.api_key.encode()).hexdigest() if config.api_key else ""
    return f"{config.provider}|{config.base_url}|{config.model}|{key_fingerprint}"


def _gateway_error(response: httpx.Response) -> tuple[str, str] | None:
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        code = str(error.get("code") or "") if isinstance(error, dict) else ""
    except (TypeError, ValueError):
        return None
    details = {
        "license_missing": "Licenza Kreluna non presente",
        "license_invalid": "Licenza Kreluna non valida",
        "license_inactive": "Licenza Kreluna sospesa o revocata",
        "license_expired": "Licenza Kreluna scaduta",
        "quota_exhausted": "Quota IA della licenza esaurita",
        "rate_limit": "Troppe richieste ravvicinate",
        "provider_authentication": "Servizio IA centrale non autorizzato",
        "provider_unavailable": "Il servizio IA non è temporaneamente disponibile",
        "provider_model_unavailable": "Il motore IA gestito non è disponibile",
        "gateway_misconfigured": "Servizio IA centrale non configurato",
    }
    return (code, details[code]) if code in details else None


async def check_ai_health(
    config: AIProviderConfig,
    *,
    client: httpx.AsyncClient | None = None,
    force: bool = False,
    timeout: float = 5.0,
) -> dict[str, Any]:
    if not config.configured:
        return _not_configured(config)
    cache_key = _cache_key(config)
    cached = _HEALTH_CACHE.get(cache_key)
    if not force and cached is not None and time.monotonic() - cached[0] < HEALTH_CACHE_SECONDS:
        return cached[1]

    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    owned = client is None
    requester = client or httpx.AsyncClient()
    try:
        response = await requester.get(_health_url(config), headers=headers, timeout=timeout)
        gateway_error = _gateway_error(response) if config.managed else None
        if gateway_error is not None:
            status, detail = gateway_error
        elif response.status_code in {401, 403}:
            status, detail = "authentication", "Chiave API rifiutata"
        elif response.status_code >= 500:
            status, detail = "provider_unavailable", "Il provider non risponde correttamente"
        elif response.status_code >= 400:
            status, detail = "health_rejected", f"Health check rifiutato ({response.status_code})"
        else:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("health payload is not an object")
            ids = _model_ids(config, payload)
            exact = config.model in ids
            ollama_tag = config.provider == "ollama" and any(
                item.split(":", 1)[0] == config.model for item in ids
            )
            if exact or ollama_tag:
                status, detail = "connected", "Provider e modello raggiungibili"
            else:
                status, detail = "model_missing", "Il modello configurato non è disponibile"
    except httpx.TimeoutException:
        status, detail = "timeout", "Health check scaduto"
    except (httpx.HTTPError, ValueError, TypeError):
        status, detail = "connection", "Connessione o risposta del provider non valida"
    finally:
        if owned:
            await requester.aclose()

    result = {
        "provider": config.provider,
        "label": config.label,
        "model": config.model,
        "configured": True,
        "connected": status == "connected",
        "status": status,
        "detail": detail,
        "managed": config.managed,
        "configurable": config.configurable,
    }
    _HEALTH_CACHE[cache_key] = (time.monotonic(), result)
    return result
