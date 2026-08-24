from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, get_actor
from app.models import License, UsedNonce, utcnow
from app.services.audit import write_audit

router = APIRouter()


class BillingEvent(BaseModel):
    id: str
    type: str
    tenant_id: str


def _verify(secret: str, body: bytes, signature: str) -> None:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("WEBHOOK_INVALID")


@router.post("/billing/webhook")
async def billing_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_kreluna_signature: Annotated[str | None, Header()] = None,
) -> dict:
    raw = await request.body()
    if not x_kreluna_signature:
        raise HTTPException(status_code=401, detail="Firma webhook assente")
    try:
        _verify(settings.director_signing_seed, raw, x_kreluna_signature)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Firma webhook non valida") from exc
    payload = json.loads(raw.decode())
    event = BillingEvent.model_validate(payload)
    duplicate = (
        await session.execute(select(UsedNonce).where(UsedNonce.nonce == f"billing:{event.id}"))
    ).scalar_one_or_none()
    license_row = (
        await session.execute(select(License).where(License.tenant_id == event.tenant_id))
    ).scalar_one_or_none()
    if license_row is None:
        raise HTTPException(status_code=404, detail="Tenant sconosciuto")
    if duplicate:
        return {"ok": True, "duplicate": True, "state": license_row.state}
    session.add(UsedNonce(nonce=f"billing:{event.id}"))

    if event.type == "invoice.paid":
        license_row.state = "active"
        license_row.grace_until = None
        result = "active"
    elif event.type in {"invoice.payment_failed", "subscription.past_due"}:
        license_row.state = "grace"
        license_row.grace_until = utcnow() + timedelta(days=7)
        result = "grace"
    elif event.type == "grace_expired":
        license_row.state = "suspended"
        result = "suspended"
    else:
        raise HTTPException(status_code=400, detail="Evento non gestito")

    await write_audit(
        session,
        tenant_id=event.tenant_id,
        actor="billing",
        action=f"billing.{event.type}",
        result=result,
        detail=event.id,
    )
    await session.commit()
    return {"ok": True, "state": license_row.state, "event_id": event.id}


@router.post("/billing/simulate/{state}")
async def simulate_license(
    state: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Ruolo insufficiente")
    if state not in {"active", "grace", "restricted", "suspended"}:
        raise HTTPException(status_code=400, detail="Stato non valido")
    row = (await session.execute(select(License).where(License.tenant_id == actor.tenant_id))).scalar_one()
    row.state = state
    await session.commit()
    return {"ok": True, "state": state}
