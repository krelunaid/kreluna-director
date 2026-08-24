from __future__ import annotations

import base64
import json
from datetime import UTC, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from kreluna_shared.crypto import b64d, decrypt_bytes, encrypt_bytes, sha256_hex, verify_bytes
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Approval, Device, Evidence, InvoiceDraft, Task, utcnow
from app.services.audit import write_audit
from app.services.ledger import create_draft, observed_from_draft, verify_invoice
from app.services.registry import hub

router = APIRouter()


class EvidenceIn(BaseModel):
    kind: str
    sha256: str
    png_b64: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestBody(BaseModel):
    device_id: str
    task_id: str
    signature: str
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evidence: list[EvidenceIn] = Field(default_factory=list)


def _verify_device(device: Device, task_id: str, signature: str) -> None:
    payload = task_id.encode()
    try:
        if not verify_bytes(b64d(device.public_key), payload, b64d(signature)):
            raise PermissionError("bad sig")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Firma dispositivo non valida") from exc


@router.post("/agent/ingest")
async def ingest(body: IngestBody, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = (await session.execute(select(Device).where(Device.id == body.device_id))).scalar_one_or_none()
    if device is None or device.status != "active":
        raise HTTPException(status_code=401, detail="Device sconosciuto o revocato")
    _verify_device(device, body.task_id, body.signature)

    task = (
        await session.execute(select(Task).where(Task.id == body.task_id, Task.tenant_id == device.tenant_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trovato")

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

    if body.ok:
        task.status = "completed"
        task.error = None
    elif (body.error or "") in {"AGENT_KILLED", "AGENT_PAUSED"}:
        # Il PC era fermo, non è un errore del lavoro: resta in coda per dopo il Riprendi.
        task.status = "queued"
        task.assigned_device_id = None
        task.error = None
    else:
        task.status = "failed"
        task.error = body.error
        device.recent_errors += 1
    task.result_json = json.dumps(body.result)
    device.busy = False
    device.active_task_id = None
    device.presence = "online" if device.id in hub.agents else device.presence

    if body.ok and task.capability == "invoice_prepare_demo":
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
    await hub.broadcast_dashboard({"type": "task_result", "task_id": task.id, "status": task.status})
    return {"ok": True, "status": task.status, "evidence_hashes": saved}


@router.post("/agent/demo-invoice/prepare")
async def agent_prepare_invoice(payload: dict[str, Any], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = await _require_device(session, payload)
    draft = create_draft(
        device.tenant_id,
        payload["client_name"],
        payload.get("description", "Consulenza"),
        float(payload["net_eur"]),
        float(payload.get("vat_rate", 0.22)),
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    observed = observed_from_draft(draft)
    expected = {
        "client": draft.client_name,
        "net": draft.net_cents / 100,
        "vat": draft.vat_cents / 100,
        "total": draft.total_cents / 100,
        "status": "draft",
    }
    return {"observed": observed, "expected": expected, "verification": verify_invoice(expected, observed)}


@router.post("/agent/demo-invoice/submit")
async def agent_submit_invoice(payload: dict[str, Any], session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    device = await _require_device(session, payload)
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


async def _require_device(session: AsyncSession, payload: dict[str, Any]) -> Device:
    device = (await session.execute(select(Device).where(Device.id == payload.get("device_id")))).scalar_one_or_none()
    if device is None or device.status != "active":
        raise HTTPException(status_code=401, detail="Device sconosciuto o revocato")
    _verify_device(device, payload.get("task_id") or payload.get("device_id"), payload.get("signature") or "")
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
