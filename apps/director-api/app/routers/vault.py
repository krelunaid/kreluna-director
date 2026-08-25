from __future__ import annotations

from typing import Annotated

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.deps import Actor, get_actor
from app.models import ClientCredential, utcnow
from app.services.audit import write_audit
from app.services.vault import (
    MAX_CSV_BYTES,
    VaultImportError,
    decrypt_credential,
    decrypt_username,
    encrypt_credential_fields,
    mask_username,
    parse_credentials_csv,
)

router = APIRouter(prefix="/vault", tags=["vault"])


def _require_owner(actor: Actor) -> None:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Solo il titolare può gestire la Cassaforte")


async def _read_csv(upload: UploadFile) -> bytes:
    name = (upload.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Carica un file CSV")
    data = await upload.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="Il CSV supera 1 MB")
    return data


@router.get("/credentials")
async def list_credentials(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_owner(actor)
    rows = (
        await session.execute(
            select(ClientCredential)
            .where(
                ClientCredential.tenant_id == actor.tenant_id,
                ClientCredential.status != "revoked",
            )
            .order_by(ClientCredential.client_name, ClientCredential.portal)
        )
    ).scalars().all()
    items = []
    for row in rows:
        try:
            username_masked = mask_username(decrypt_username(row))
            status = row.status
        except (ValueError, UnicodeDecodeError, InvalidTag):
            username_masked = "non leggibile"
            status = "error"
        items.append(
            {
                "id": row.id,
                "client_name": row.client_name,
                "portal": row.portal,
                "credential_label": row.credential_label,
                "secret_kind": row.secret_kind,
                "username_masked": username_masked,
                "status": status,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return {"credentials": items, "count": len(items)}


@router.post("/import/preview")
async def preview_import(
    actor: Annotated[Actor, Depends(get_actor)],
    file: Annotated[UploadFile, File()],
) -> dict:
    _require_owner(actor)
    try:
        rows, warnings = parse_credentials_csv(await _read_csv(file))
    except VaultImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "recognized": len(rows),
        "rows": [row.public() for row in rows[:50]],
        "warnings": warnings[:50],
        "truncated": len(rows) > 50,
        "processed_locally": True,
        "sent_to_ai": False,
    }


@router.post("/import")
async def import_credentials(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> dict:
    _require_owner(actor)
    try:
        parsed, warnings = parse_credentials_csv(await _read_csv(file))
    except VaultImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = 0
    updated = 0
    for item in parsed:
        row = (
            await session.execute(
                select(ClientCredential).where(
                    ClientCredential.tenant_id == actor.tenant_id,
                    ClientCredential.client_key == item.client_key,
                    ClientCredential.portal == item.portal,
                    ClientCredential.credential_label == item.credential_label,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ClientCredential(
                tenant_id=actor.tenant_id,
                client_name=item.client_name,
                client_key=item.client_key,
                portal=item.portal,
                credential_label=item.credential_label,
                secret_kind=item.secret_kind,
                username_ciphertext="",
                secret_ciphertext="",
                updated_by=actor.user_id,
            )
            session.add(row)
            created += 1
        else:
            updated += 1
        row.client_name = item.client_name
        row.secret_kind = item.secret_kind
        row.status = "ready"
        row.updated_by = actor.user_id
        row.updated_at = utcnow()
        encrypt_credential_fields(row, username=item.username, secret=item.secret)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="vault.csv_import",
        result="ok",
        detail=f"created={created};updated={updated};rejected={len(warnings)}",
    )
    await session.commit()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "rejected": len(warnings),
        "warnings": warnings[:50],
        "source_file_retained": False,
        "sent_to_ai": False,
    }


@router.post("/credentials/{credential_id}/check")
async def check_credential(
    credential_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_owner(actor)
    row = (
        await session.execute(
            select(ClientCredential).where(
                ClientCredential.id == credential_id,
                ClientCredential.tenant_id == actor.tenant_id,
                ClientCredential.status != "revoked",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Accesso non trovato")
    try:
        username, secret = decrypt_credential(row)
        ready = bool(username and secret)
    except (ValueError, UnicodeDecodeError, InvalidTag):
        ready = False
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="vault.integrity_check",
        result="ok" if ready else "error",
        detail=f"credential_id={row.id}",
    )
    await session.commit()
    return {
        "ok": ready,
        "state": "ready" if ready else "error",
        "detail": (
            "Credenziale cifrata integra. Il portale non è stato contattato."
            if ready
            else "La credenziale non è più leggibile: sostituiscila."
        ),
    }


@router.delete("/credentials/{credential_id}")
async def revoke_credential(
    credential_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_owner(actor)
    row = (
        await session.execute(
            select(ClientCredential).where(
                ClientCredential.id == credential_id,
                ClientCredential.tenant_id == actor.tenant_id,
                ClientCredential.status != "revoked",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Accesso non trovato")
    row.status = "revoked"
    row.username_ciphertext = ""
    row.secret_ciphertext = ""
    row.updated_by = actor.user_id
    row.updated_at = utcnow()
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="vault.credential_revoke",
        result="ok",
        detail=f"credential_id={row.id}",
    )
    await session.commit()
    return {"ok": True, "state": "revoked"}


@router.get("/template.csv", response_class=PlainTextResponse)
async def csv_template(actor: Annotated[Actor, Depends(get_actor)]) -> PlainTextResponse:
    _require_owner(actor)
    body = (
        "cliente;portale;username;password;tipo_segreto;etichetta\n"
        "Esempio Cliente;webdesk;utente@example.it;SOSTITUISCI;password;principale\n"
    )
    return PlainTextResponse(
        body,
        headers={"Content-Disposition": 'attachment; filename="kreluna-cassaforte-modello.csv"'},
    )
