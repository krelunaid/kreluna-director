from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, require_roles
from app.models import GmailConnection, WebdeskMailChallenge, WebdeskMailPolicy
from app.services.gmail import (
    GmailError,
    begin_authorization,
    complete_authorization,
    configuration_status,
    disconnect,
    verify_connection,
)

router = APIRouter(prefix="/integrations/gmail", tags=["gmail"])


@router.get("/status")
async def status(
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = configuration_status(settings)
    row = await session.get(GmailConnection, actor.tenant_id)
    result.update(connected=row is not None, email=row.email if row else "")
    policy = await session.get(WebdeskMailPolicy, actor.tenant_id)
    result["webdesk_codes_enabled"] = bool(policy and policy.enabled)
    result["available"] = bool(row and policy and policy.enabled)
    result["message"] = (
        ("Gmail collegato. Codici Webdesk automatici autorizzati." if result["available"] else
         "Gmail collegato. Recupero automatico Webdesk disattivato.")
        if row else "Premi Collega Gmail e autorizza l’account nel browser."
        if result["configured"] else result["message"]
    )
    return result


class WebdeskPolicyInput(BaseModel):
    enabled: bool


@router.put("/webdesk-policy")
async def webdesk_policy(body: WebdeskPolicyInput,
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if body.enabled and not await session.get(GmailConnection, actor.tenant_id):
        raise HTTPException(409, "Collega prima Gmail.")
    policy = await session.get(WebdeskMailPolicy, actor.tenant_id)
    if policy is None:
        policy = WebdeskMailPolicy(tenant_id=actor.tenant_id)
        session.add(policy)
    policy.enabled, policy.updated_by = body.enabled, actor.user_id
    challenge = await session.get(WebdeskMailChallenge, actor.tenant_id)
    if challenge:
        challenge.consumed = True
    await session.commit()
    return {"enabled": body.enabled}


class ConnectInput(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    consent_readonly: bool = False


@router.post("/verify")
async def verify(
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        email = await verify_connection(session, settings, actor.tenant_id)
    except GmailError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"verified": True, "email": email, "message": "Accesso Gmail verificato e rinnovato senza nuovo consenso."}


@router.post("/connect")
async def connect(
    body: ConnectInput,
    request: Request,
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if not body.consent_readonly:
        raise HTTPException(400, "Conferma di aver letto i permessi Gmail richiesti.")
    if settings.gmail_oauth_client_type == "desktop" and (
        not request.client or request.client.host not in {"127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Collega Gmail dal Mac dove è installato Director.")
    try:
        url = await begin_authorization(session, settings, actor, body.email)
    except GmailError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"authorization_url": url}


@router.get("/callback", response_class=HTMLResponse)
async def callback(request: Request, session: Annotated[AsyncSession, Depends(get_session)]):
    # Access logs must not retain Google's authorization code or state.
    params = request.query_params
    request.scope["query_string"] = b""
    message = "Collegamento annullato o non valido. Torna alle Impostazioni di Kreluna Director."
    success = False
    state, code = params.get("state", ""), params.get("code", "")
    if 1 <= len(state) <= 200 and len(code) <= 4096:
        try:
            await complete_authorization(session, settings, state, code)
            success = True
            message = "Gmail collegato. Torna alle Impostazioni di Kreluna Director e premi Verifica."
        except GmailError as exc:
            message = str(exc)
    from html import escape
    return HTMLResponse(
        "<!doctype html><html lang='it'><meta charset='utf-8'><title>Kreluna Director</title>"
        f"<h1>{'Collegamento riuscito' if success else 'Collegamento non completato'}</h1>"
        f"<p>{escape(message)}</p><p>Nessuna fattura salvata, emessa o inviata da questa operazione.</p></html>",
        status_code=200 if success else 400,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"},
    )


@router.delete("/connection")
async def remove_connection(
    actor: Annotated[Actor, Depends(require_roles("studio_owner", "platform_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    revoked = await disconnect(session, settings, actor.tenant_id)
    return {"connected": False, "revoked": revoked, "message": "Gmail scollegato." if revoked else
            "Dati locali rimossi. Revoca anche l’accesso Kreluna nelle impostazioni del tuo account Google."}
