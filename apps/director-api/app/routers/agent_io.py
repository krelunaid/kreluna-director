from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Request
from kreluna_shared.crypto import (
    agent_http_payload,
    b64d,
    canonical_json_bytes,
    decrypt_bytes,
    encrypt_bytes,
    sha256_hex,
    verify_bytes,
)
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import (
    Approval,
    ClientCredential,
    Device,
    Evidence,
    GmailConnection,
    InvoiceDraft,
    Task,
    UsedNonce,
    WebdeskMailChallenge,
    WebdeskMailPolicy,
    as_utc,
    new_id,
    utcnow,
)
from app.services.audit import write_audit
from app.services.gmail import GmailError, digest
from app.services.ledger import create_draft, observed_from_draft, verify_invoice
from app.services.orchestrator import INTERRUPT_REQUEUE_ERRORS
from app.services.registry import hub
from app.services.vault import (
    client_key_for_name,
    decrypt_credential,
    decrypt_portal_account,
    decrypt_username,
)
from app.services.webdesk_mail import read_validation_code

router = APIRouter()


class EvidenceIn(BaseModel):
    kind: str
    sha256: str
    png_b64: str | None = Field(default=None, max_length=12_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestBody(BaseModel):
    device_id: str
    task_id: str
    nonce: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    sent_at: int
    signature: str
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evidence: list[EvidenceIn] = Field(default_factory=list)


class CredentialLeaseBody(BaseModel):
    device_id: str
    task_id: str
    nonce: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
    sent_at: int
    signature: str


TASK_PORTALS = {
    "f24-ipsoa": {"ipsoa", "telematico"},
    "contabilita-ipsoa": {"ipsoa"},
    "fatture-webdesk": {"webdesk", "ade"},
    "visure-cgn": {"cgn"},
    "camerali-cgn": {"cgn", "comunica"},
    "contratti-ade": {"ade"},
}


async def _verify_agent_request(
    session: AsyncSession,
    device: Device,
    path: str,
    payload: dict[str, Any],
) -> None:
    nonce = str(payload.get("nonce") or "")
    sent_at = payload.get("sent_at")
    if len(nonce) != 32 or any(char not in "0123456789abcdef" for char in nonce):
        raise HTTPException(status_code=401, detail="Nonce Agent non valido")
    if not isinstance(sent_at, int) or abs(int(utcnow().timestamp()) - sent_at) > 180:
        raise HTTPException(status_code=401, detail="Richiesta Agent scaduta")
    signed = {key: value for key, value in payload.items() if key != "signature"}
    try:
        if not verify_bytes(
            b64d(device.public_key),
            agent_http_payload(path, signed),
            b64d(str(payload.get("signature") or "")),
        ):
            raise PermissionError("bad sig")
    except (ValueError, TypeError, binascii.Error, PermissionError) as exc:
        raise HTTPException(status_code=401, detail="Firma dispositivo non valida") from exc
    request_nonce = f"agent-http:{device.id}:{nonce}"
    replay = (
        await session.execute(select(UsedNonce).where(UsedNonce.nonce == request_nonce))
    ).scalar_one_or_none()
    if replay is not None:
        raise HTTPException(status_code=409, detail="Richiesta Agent già ricevuta")
    session.add(UsedNonce(nonce=request_nonce))


async def _credential_for_task(
    session: AsyncSession,
    body: CredentialLeaseBody,
    *,
    path: str,
) -> tuple[Device, Task, ClientCredential]:
    device = (
        await session.execute(select(Device).where(Device.id == body.device_id))
    ).scalar_one_or_none()
    if device is None or device.status != "active" or device.killed or device.paused:
        raise HTTPException(status_code=401, detail="Agent non autorizzato")
    await _verify_agent_request(session, device, path, body.model_dump(mode="json"))
    task = (
        await session.execute(
            select(Task).where(Task.id == body.task_id, Task.tenant_id == device.tenant_id)
        )
    ).scalar_one_or_none()
    if (
        task is None
        or task.assigned_device_id != device.id
        or task.capability != "portal_open"
        or task.status not in {"assigned", "running"}
    ):
        raise HTTPException(status_code=403, detail="Il task non può usare Fort Knox")
    args = json.loads(task.args_json or "{}")
    if args.get("use_saved_access") is not True:
        raise HTTPException(status_code=403, detail="L'uso di Fort Knox non è stato richiesto")
    portal_key = str(args.get("portal") or "")
    client_key = client_key_for_name(str(args.get("query") or ""))
    allowed_portals = TASK_PORTALS.get(portal_key, set())
    if not allowed_portals or (not client_key and portal_key != "fatture-webdesk"):
        raise HTTPException(status_code=409, detail="Cliente o portale non supportato")
    credential = (
        await session.execute(
            select(ClientCredential)
            .where(
                ClientCredential.tenant_id == device.tenant_id,
                ClientCredential.client_key == client_key,
                ClientCredential.portal.in_(allowed_portals),
                ClientCredential.status == "ready",
            )
            .order_by(ClientCredential.credential_label)
        )
    ).scalars().first()
    # Webdesk è normalmente un accesso unico dello studio, non una password
    # diversa per ogni destinatario della fattura. Se il nome del destinatario
    # non coincide, usa l'unico accesso Webdesk disponibile; con più accessi
    # resta obbligatoria una corrispondenza esplicita per evitare ambiguità.
    if credential is None and portal_key == "fatture-webdesk":
        candidates = (
            await session.execute(
                select(ClientCredential)
                .where(
                    ClientCredential.tenant_id == device.tenant_id,
                    ClientCredential.portal.in_(allowed_portals),
                    ClientCredential.status == "ready",
                )
                .order_by(ClientCredential.credential_label)
            )
        ).scalars().all()
        official = [
            item
            for item in candidates
            if (urlparse(item.portal_url).hostname or "").lower()
            in {"app.webdesk.it", "sme.genya.it"}
        ]
        if len(official) == 1:
            credential = official[0]
        elif len(candidates) == 1:
            credential = candidates[0]
    if credential is None:
        raise HTTPException(status_code=404, detail="Nessun accesso salvato per cliente e portale")
    return device, task, credential


def _credential_transport_allowed(request: Request) -> bool:
    from urllib.parse import urlparse

    public = urlparse(settings.director_public_url)
    if public.scheme == "https":
        return True
    client_host = (request.client.host if request.client else "").lower()
    return public.scheme == "http" and client_host in {"127.0.0.1", "::1", "localhost", "testclient"}


class WebdeskCodeBody(CredentialLeaseBody):
    recipient: str = Field(default="", max_length=200)
    challenge_id: str = Field(default="", max_length=36)


async def _webdesk_mail_context(session, body, request, path):
    if not _credential_transport_allowed(request):
        raise HTTPException(403, "Il codice richiede un canale protetto.")
    device, task, credential = await _credential_for_task(session, body, path=path)
    if json.loads(task.args_json).get("portal") != "fatture-webdesk":
        raise HTTPException(403, "Solo validazione Webdesk.")
    policy = await session.get(WebdeskMailPolicy, device.tenant_id)
    connection = await session.get(GmailConnection, device.tenant_id)
    if not policy or not policy.enabled or not connection:
        raise HTTPException(409, "Recupero codice Webdesk non attivo nelle Impostazioni Gmail.")
    return device, task, connection, credential


@router.post("/agent/webdesk-code/start")
async def start_webdesk_code(body: WebdeskCodeBody, request: Request,
                             session: Annotated[AsyncSession, Depends(get_session)]):
    device, task, connection, _ = await _webdesk_mail_context(session, body, request, "/agent/webdesk-code/start")
    if body.recipient.strip().lower() != connection.email:
        raise HTTPException(409, "Webdesk invia il codice a un account diverso da Gmail collegato.")
    now = utcnow()
    existing = await session.get(WebdeskMailChallenge, device.tenant_id)
    # A delivered/closed challenge must not block a subsequent job. The
    # per-task nonce below still prevents requesting twice for the same job.
    if existing and not existing.consumed and as_utc(existing.expires_at) > now:
        raise HTTPException(409, "Una validazione Webdesk è già in corso. Attendi prima di riprovare.")
    if existing:
        await session.delete(existing)
        await session.flush()
    row = WebdeskMailChallenge(tenant_id=device.tenant_id, id=new_id(), device_id=device.id,
                              task_id=task.id, connection_version=digest(connection.refresh_ciphertext),
                              created_at=now, expires_at=now+timedelta(minutes=3), next_poll_at=now)
    session.add(row)
    session.add(UsedNonce(nonce=f"webdesk-code-start:{task.id}"))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Validazione già richiesta per questo lavoro.") from None
    return {"challenge_id": row.id, "expires_in_seconds": 180}


@router.post("/agent/webdesk-code/poll")
async def poll_webdesk_code(body: WebdeskCodeBody, request: Request,
                            session: Annotated[AsyncSession, Depends(get_session)]):
    device, task, connection, credential = await _webdesk_mail_context(session, body, request, "/agent/webdesk-code/poll")
    now = utcnow()
    row = await session.get(WebdeskMailChallenge, device.tenant_id)
    if (not row or row.id != body.challenge_id or row.task_id != task.id or row.device_id != device.id
            or row.consumed or as_utc(row.expires_at) <= now
            or row.connection_version != digest(connection.refresh_ciphertext)):
        raise HTTPException(409, "Validazione scaduta, annullata o già utilizzata.")
    claimed = await session.execute(update(WebdeskMailChallenge).where(
        WebdeskMailChallenge.tenant_id == device.tenant_id,
        WebdeskMailChallenge.id == body.challenge_id,
        WebdeskMailChallenge.consumed.is_(False),
        WebdeskMailChallenge.attempts < 30,
        WebdeskMailChallenge.next_poll_at <= now,
    ).values(attempts=WebdeskMailChallenge.attempts+1, next_poll_at=now+timedelta(seconds=5))
      .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        raise HTTPException(429, "Attendi prima del prossimo controllo del codice.")
    await session.commit()
    try:
        login = decrypt_username(credential)
        match = await read_validation_code(settings, connection, as_utc(row.created_at), now, login)
    except (GmailError, ValueError, InvalidTag):
        await session.execute(update(WebdeskMailChallenge).where(
            WebdeskMailChallenge.tenant_id == device.tenant_id,
            WebdeskMailChallenge.id == body.challenge_id,
        ).values(consumed=True))
        await session.commit()
        raise HTTPException(409, "Codice Webdesk non verificato: procedura fermata.") from None
    if match is None:
        await session.refresh(task)
        await session.refresh(row)
        if task.status not in {"assigned", "running"} or row.consumed or as_utc(row.expires_at) <= utcnow():
            raise HTTPException(409, "Lavoro terminato o validazione scaduta.")
        return {"pending": True}
    message_id, code = match
    # Atomically consume, then recheck authority after Gmail network I/O.
    consumed = await session.execute(update(WebdeskMailChallenge).where(
        WebdeskMailChallenge.tenant_id == device.tenant_id,
        WebdeskMailChallenge.id == body.challenge_id,
        WebdeskMailChallenge.consumed.is_(False),
        WebdeskMailChallenge.expires_at > utcnow(),
    ).values(consumed=True).execution_options(synchronize_session=False))
    await session.refresh(device)
    await session.refresh(task)
    policy = await session.get(WebdeskMailPolicy, device.tenant_id, populate_existing=True)
    current = await session.get(GmailConnection, device.tenant_id, populate_existing=True)
    if (consumed.rowcount != 1 or device.killed or device.paused or device.status != "active"
            or task.status not in {"assigned", "running"} or task.assigned_device_id != device.id
            or not policy or not policy.enabled or not current
            or digest(current.refresh_ciphertext) != row.connection_version):
        await session.rollback()
        raise HTTPException(409, "Lavoro o autorizzazione non più attivi.")
    session.add(UsedNonce(nonce=f"webdesk-mail:{device.tenant_id}:{digest(message_id)}"))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Messaggio già utilizzato.") from None
    from fastapi.responses import JSONResponse
    return JSONResponse({"pending": False, "code": code}, headers={"Cache-Control": "no-store"})


@router.post("/agent/credential-lease")
async def credential_lease(
    body: CredentialLeaseBody,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Release one credential once, only to the device already assigned to the task."""

    if not _credential_transport_allowed(request):
        raise HTTPException(status_code=409, detail="Fort Knox richiede una connessione HTTPS")
    device, task, credential = await _credential_for_task(
        session,
        body,
        path="/agent/credential-lease",
    )
    nonce = f"vault-task:{task.id}"
    already_used = (
        await session.execute(select(UsedNonce).where(UsedNonce.nonce == nonce))
    ).scalar_one_or_none()
    if already_used is not None:
        raise HTTPException(status_code=409, detail="Accesso già consegnato per questo lavoro")
    try:
        username, secret = decrypt_credential(credential)
    except (ValueError, UnicodeDecodeError, InvalidTag) as exc:
        raise HTTPException(status_code=409, detail="Accesso cifrato non leggibile") from exc
    session.add(UsedNonce(nonce=nonce))
    await write_audit(
        session,
        tenant_id=device.tenant_id,
        actor=device.agent_id,
        action="vault.credential_lease",
        result="ok",
        device_id=device.id,
        task_id=task.id,
        capability=task.capability,
        detail=f"credential_id={credential.id}",
    )
    await session.commit()
    return {
        "username": username,
        "secret": secret,
        "secret_kind": credential.secret_kind,
        "credential_label": credential.credential_label,
        "portal_account": decrypt_portal_account(credential),
        "expires_in_seconds": 30,
        "single_use": True,
    }


@router.post("/agent/portal-location")
async def portal_location(
    body: CredentialLeaseBody,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Tell the assigned Agent where to open the portal without releasing secrets."""

    if not _credential_transport_allowed(request):
        raise HTTPException(status_code=409, detail="Fort Knox richiede una connessione HTTPS")
    device, task, credential = await _credential_for_task(
        session,
        body,
        path="/agent/portal-location",
    )
    await write_audit(
        session,
        tenant_id=device.tenant_id,
        actor=device.agent_id,
        action="vault.portal_location",
        result="ok",
        device_id=device.id,
        task_id=task.id,
        capability=task.capability,
        detail=f"credential_id={credential.id};link={'yes' if credential.portal_url else 'no'}",
    )
    await session.commit()
    return {
        "portal_url": credential.portal_url,
        "configured": bool(credential.portal_url),
        "sent_to_ai": False,
    }


@router.post("/agent/ingest")
async def ingest(body: IngestBody, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = (await session.execute(select(Device).where(Device.id == body.device_id))).scalar_one_or_none()
    if device is None or device.status != "active":
        raise HTTPException(status_code=401, detail="Device sconosciuto o revocato")
    now = int(utcnow().timestamp())
    if abs(now - body.sent_at) > 180:
        raise HTTPException(status_code=401, detail="Risultato Agent scaduto")
    signed = body.model_dump(mode="json", exclude={"signature"})
    try:
        valid_signature = verify_bytes(
            b64d(device.public_key),
            canonical_json_bytes(signed),
            b64d(body.signature),
        )
    except (ValueError, TypeError, binascii.Error):
        valid_signature = False
    if not valid_signature:
        raise HTTPException(status_code=401, detail="Firma risultato Agent non valida")
    result_nonce = f"agent-result:{device.id}:{body.nonce}"
    replay = (
        await session.execute(select(UsedNonce).where(UsedNonce.nonce == result_nonce))
    ).scalar_one_or_none()
    if replay is not None:
        raise HTTPException(status_code=409, detail="Risultato Agent già ricevuto")

    task = (
        await session.execute(select(Task).where(Task.id == body.task_id, Task.tenant_id == device.tenant_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trovato")
    if task.assigned_device_id != device.id:
        raise HTTPException(status_code=403, detail="Il task non è assegnato a questo Agent")
    if task.status not in {"assigned", "running"}:
        raise HTTPException(status_code=409, detail="Il task non accetta più risultati")
    session.add(UsedNonce(nonce=result_nonce))

    settings.evidence_path.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for item in body.evidence:
        if not item.png_b64:
            continue
        raw = base64.b64decode(item.png_b64)
        digest = sha256_hex(raw)
        if digest != item.sha256:
            raise HTTPException(status_code=400, detail="Hash evidenza non corrispondente")
        storage_key = f"{device.tenant_id}/{task.id}/{digest}.bin"
        dest = settings.evidence_path / storage_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(encrypt_bytes(settings.director_evidence_key, raw))
        session.add(
            Evidence(
                tenant_id=device.tenant_id,
                task_id=task.id,
                device_id=device.id,
                kind=item.kind,
                sha256=digest,
                storage_key=storage_key,
                meta_json=json.dumps(item.metadata),
            )
        )
        saved.append(digest)

    if body.result.get("outcome") == "blocked":
        task.status = "blocked"
        task.error = str(body.result.get("message") or body.error or "Lavoro non completato")
    elif body.ok and body.result.get("ok", True) is not False:
        task.status = "completed"
        task.error = None
    elif (body.error or "") in INTERRUPT_REQUEUE_ERRORS:
        # PC fermo o assistenza remota: il lavoro resta in coda per Riprendi lavoro.
        task.status = "queued"
        task.assigned_device_id = None
        task.error = None
    else:
        task.status = "failed"
        task.error = _readable_error(body.error, device)
        device.recent_errors += 1
    task.result_json = json.dumps(body.result)
    # A terminal outcome also closes any outstanding email challenge. Never
    # leave a failed job looking as if it is still waiting for a code.
    await session.execute(update(WebdeskMailChallenge).where(
        WebdeskMailChallenge.task_id == task.id,
        WebdeskMailChallenge.device_id == device.id,
        WebdeskMailChallenge.tenant_id == device.tenant_id,
        WebdeskMailChallenge.consumed.is_(False),
    ).values(consumed=True))
    device.busy = False
    device.active_task_id = None
    device.presence = "online" if device.id in hub.agents else device.presence

    if task.status == "completed" and task.capability == "invoice_prepare_demo":
        observed = body.result.get("observed") or {}
        expected = body.result.get("expected") or {}
        verification = body.result.get("verification") or verify_invoice(expected, observed)
        if not verification.get("ok"):
            task.status = "blocked"
            task.error = "invoice_mismatch"
        else:
            session.add(
                Approval(
                    tenant_id=device.tenant_id,
                    task_id=task.id,
                    action="invoice_submit_demo",
                    preview_json=json.dumps(
                        {
                            "observed": observed,
                            "expected": expected,
                            "verification": verification,
                            "draft_id": observed.get("draft_id"),
                        }
                    ),
                    token_nonce="pending",
                    expires_at=utcnow() + timedelta(minutes=30),
                )
            )
            task.status = "waiting_approval"
            task.needs_approval = True

    await write_audit(
        session,
        tenant_id=device.tenant_id,
        actor=device.agent_id,
        action="task.result",
        result=task.status,
        device_id=device.id,
        task_id=task.id,
        capability=task.capability,
        detail=body.error or "",
    )
    await session.commit()
    await hub.broadcast_dashboard(
        device.tenant_id,
        {"type": "task_result", "task_id": task.id, "status": task.status},
    )
    return {"ok": True, "status": task.status, "evidence_hashes": saved}


@router.post("/agent/demo-invoice/prepare")
async def agent_prepare_invoice(payload: dict[str, Any], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = await _require_device(session, payload, "/agent/demo-invoice/prepare")
    draft = create_draft(
        device.tenant_id,
        payload["client_name"],
        payload.get("description", "Consulenza"),
        float(payload["net_eur"]),
        float(payload.get("vat_rate", 0.22)),
        account_name=str(payload.get("account_name") or ""),
        vat_note=str(payload.get("vat_note") or ""),
        vat_eur=float(payload["vat_eur"]) if payload.get("vat_eur") is not None else None,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    observed = observed_from_draft(draft)
    expected = {
        "account": draft.account_name,
        "client": draft.client_name,
        "net": draft.net_cents / 100,
        "vat": draft.vat_cents / 100,
        "vat_note": draft.vat_note,
        "total": draft.total_cents / 100,
        "status": "draft",
    }
    return {"observed": observed, "expected": expected, "verification": verify_invoice(expected, observed)}


@router.post("/agent/demo-invoice/submit")
async def agent_submit_invoice(payload: dict[str, Any], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = await _require_device(session, payload, "/agent/demo-invoice/submit")
    draft = (
        await session.execute(
            select(InvoiceDraft).where(
                InvoiceDraft.id == payload["draft_id"],
                InvoiceDraft.tenant_id == device.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="Bozza non trovata")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Già emessa")
    draft.status = "issued"
    await session.commit()
    return {"observed": observed_from_draft(draft)}


def _readable_error(error: str | None, device: Device) -> str:
    """Gli errori li legge il titolare, non un programmatore."""

    raw = (error or "").strip()
    if raw == "CAPABILITY_NOT_ALLOWED":
        from app.services.agents import _needs_update

        if _needs_update(device):
            return f"{device.display_name or device.agent_id} ha un Kreluna Agent vecchio: installa la versione nuova."
        return f"{device.display_name or device.agent_id} non è il PC che fa questo lavoro."
    if raw == "NOT_READY":
        return "Quel PC si è appena collegato: riprova."
    if raw == "AGENT_REMOTE":
        return "Assistenza remota aperta: il lavoro è rimasto in attesa. Chiudi lo schermo remoto e premi Riprendi lavoro."
    return raw or "Errore senza spiegazione dal PC."


async def _require_device(session: AsyncSession, payload: dict[str, Any], path: str) -> Device:
    device = (await session.execute(select(Device).where(Device.id == payload.get("device_id")))).scalar_one_or_none()
    if device is None or device.status != "active":
        raise HTTPException(status_code=401, detail="Device sconosciuto o revocato")
    task_id = str(payload.get("task_id") or "")
    await _verify_agent_request(session, device, path, payload)
    task = (
        await session.execute(
            select(Task).where(
                Task.id == task_id,
                Task.tenant_id == device.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if (
        task is None
        or task.assigned_device_id != device.id
        or task.status not in {"assigned", "running"}
    ):
        raise HTTPException(status_code=403, detail="Task non assegnato a questo Agent")
    return device


def purge_expired_evidence(evidence_dir: Path, rows: list[Evidence], now, retention_hours: int) -> list[Evidence]:
    cutoff = now - timedelta(hours=retention_hours)
    deleted = []
    for item in rows:
        created = item.created_at
        if created.tzinfo is None:

            created = created.replace(tzinfo=UTC)
        if item.deleted_at is None and created < cutoff:
            item.deleted_at = now
            path = evidence_dir / item.storage_key
            if path.exists():
                path.unlink()
            deleted.append(item)
    return deleted


def read_evidence_bytes(storage_path: Path, secret: str) -> bytes:
    return decrypt_bytes(secret, storage_path.read_bytes())
