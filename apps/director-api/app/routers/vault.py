from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, get_actor
from app.models import ClientCredential, VaultPin, as_utc, utcnow
from app.security import hash_password, issue_session, read_session, verify_password
from app.services.audit import write_audit
from app.services.vault import (
    MAX_CSV_BYTES,
    VaultImportError,
    decrypt_credential,
    decrypt_username,
    encrypt_credential_fields,
    mask_username,
    normalize_credential,
    parse_credentials_csv,
)

router = APIRouter(prefix="/vault", tags=["vault"])
VAULT_GRANT_TTL_SECONDS = 10 * 60
VAULT_MAX_PIN_ATTEMPTS = 5
VAULT_LOCK_SECONDS = 5 * 60


class VaultCredentialWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_name: str = Field(min_length=1, max_length=200)
    portal: str = Field(min_length=1, max_length=80)
    portal_url: str = Field(default="", max_length=1000)
    username: str = Field(min_length=1, max_length=320)
    secret: SecretStr = Field(min_length=1, max_length=2048)
    secret_kind: str = Field(default="password", min_length=1, max_length=40)
    credential_label: str = Field(default="principale", min_length=1, max_length=120)


class VaultPinWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: SecretStr = Field(min_length=6, max_length=6)


def _require_owner(actor: Actor) -> None:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Solo il titolare può gestire Fort Knox")


def _pin_value(body: VaultPinWrite) -> str:
    pin = body.pin.get_secret_value()
    if len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        raise HTTPException(status_code=400, detail="Il PIN deve contenere esattamente 6 cifre")
    return pin


def _require_vault_grant(actor: Actor, grant: str | None) -> None:
    if not grant:
        raise HTTPException(status_code=423, detail="Fort Knox è chiuso: inserisci il PIN")
    try:
        claims = read_session(settings.director_session_secret, grant)
    except (PermissionError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=423, detail="Sblocco Fort Knox scaduto") from exc
    if (
        claims.get("scope") != "fort_knox"
        or claims.get("tenant_id") != actor.tenant_id
        or claims.get("user_id") != actor.user_id
    ):
        raise HTTPException(status_code=423, detail="Sblocco Fort Knox non valido")


@router.get("/pin/status")
async def pin_status(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_owner(actor)
    row = await session.get(VaultPin, actor.tenant_id)
    retry_after = 0
    if row and row.locked_until:
        retry_after = max(0, int((as_utc(row.locked_until) - utcnow()).total_seconds()))
    return {"configured": row is not None, "locked": retry_after > 0, "retry_after": retry_after}


@router.post("/pin/configure", status_code=201)
async def configure_pin(
    body: VaultPinWrite,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Set the first PIN. Changing it later requires a separate recovery flow."""

    _require_owner(actor)
    if await session.get(VaultPin, actor.tenant_id) is not None:
        raise HTTPException(status_code=409, detail="Il PIN Fort Knox è già configurato")
    row = VaultPin(
        tenant_id=actor.tenant_id,
        pin_hash=hash_password(_pin_value(body)),
        updated_by=actor.user_id,
    )
    session.add(row)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="fort_knox.pin_configure",
        result="ok",
        detail="pin_hash=argon2id",
    )
    await session.commit()
    return {"ok": True, "configured": True}


@router.post("/unlock")
async def unlock_vault(
    body: VaultPinWrite,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_owner(actor)
    row = await session.get(VaultPin, actor.tenant_id)
    if row is None:
        raise HTTPException(status_code=409, detail="Configura prima il PIN Fort Knox")
    now = utcnow()
    if row.locked_until and as_utc(row.locked_until) > now:
        retry_after = int((as_utc(row.locked_until) - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Troppi tentativi. Riprova tra {max(1, retry_after)} secondi",
        )
    pin = _pin_value(body)
    if not verify_password(pin, row.pin_hash):
        row.failed_attempts += 1
        locked = row.failed_attempts >= VAULT_MAX_PIN_ATTEMPTS
        if locked:
            row.locked_until = now + timedelta(seconds=VAULT_LOCK_SECONDS)
        row.updated_at = now
        await write_audit(
            session,
            tenant_id=actor.tenant_id,
            actor=actor.user_id,
            action="fort_knox.unlock",
            result="denied",
            detail=f"attempt={row.failed_attempts};locked={str(locked).lower()}",
        )
        await session.commit()
        if locked:
            raise HTTPException(
                status_code=429,
                detail="Fort Knox bloccato per 5 minuti dopo troppi tentativi",
            )
        raise HTTPException(status_code=403, detail="PIN non valido")
    row.failed_attempts = 0
    row.locked_until = None
    row.updated_at = now
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="fort_knox.unlock",
        result="ok",
        detail=f"ttl_seconds={VAULT_GRANT_TTL_SECONDS}",
    )
    await session.commit()
    grant = issue_session(
        settings.director_session_secret,
        {
            "scope": "fort_knox",
            "tenant_id": actor.tenant_id,
            "user_id": actor.user_id,
        },
        ttl=VAULT_GRANT_TTL_SECONDS,
    )
    return {"ok": True, "grant": grant, "expires_in": VAULT_GRANT_TTL_SECONDS}


def _validated(body: VaultCredentialWrite):
    try:
        return normalize_credential(
            client_name=body.client_name,
            portal=body.portal,
            portal_url=body.portal_url,
            username=body.username,
            secret=body.secret.get_secret_value(),
            secret_kind=body.secret_kind,
            credential_label=body.credential_label,
        )
    except VaultImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _find_same_credential(
    session: AsyncSession,
    *,
    tenant_id: str,
    client_key: str,
    portal: str,
    credential_label: str,
) -> ClientCredential | None:
    return (
        await session.execute(
            select(ClientCredential).where(
                ClientCredential.tenant_id == tenant_id,
                ClientCredential.client_key == client_key,
                ClientCredential.portal == portal,
                ClientCredential.credential_label == credential_label,
            )
        )
    ).scalar_one_or_none()


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
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
                "portal_url": row.portal_url,
                "credential_label": row.credential_label,
                "secret_kind": row.secret_kind,
                "username_masked": username_masked,
                "status": status,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return {"credentials": items, "count": len(items)}


@router.post("/credentials", status_code=201)
async def create_credential(
    body: VaultCredentialWrite,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    """Create one encrypted credential without ever returning its plaintext."""

    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
    item = _validated(body)
    row = await _find_same_credential(
        session,
        tenant_id=actor.tenant_id,
        client_key=item.client_key,
        portal=item.portal,
        credential_label=item.credential_label,
    )
    if row is not None and row.status != "revoked":
        raise HTTPException(
            status_code=409,
            detail="Questo accesso esiste già in Fort Knox: usa Aggiorna.",
        )
    if row is None:
        row = ClientCredential(
            tenant_id=actor.tenant_id,
            client_name=item.client_name,
            client_key=item.client_key,
            portal=item.portal,
            portal_url=item.portal_url,
            credential_label=item.credential_label,
            secret_kind=item.secret_kind,
            username_ciphertext="",
            secret_ciphertext="",
            updated_by=actor.user_id,
        )
        session.add(row)
    row.client_name = item.client_name
    row.portal_url = item.portal_url
    row.secret_kind = item.secret_kind
    row.status = "ready"
    row.updated_by = actor.user_id
    row.updated_at = utcnow()
    encrypt_credential_fields(row, username=item.username, secret=item.secret)
    await session.flush()
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="fort_knox.credential_create",
        result="ok",
        detail=f"credential_id={row.id};portal={row.portal}",
    )
    await session.commit()
    return {
        "ok": True,
        "id": row.id,
        "state": "ready",
        "username_masked": mask_username(item.username),
        "sent_to_ai": False,
    }


@router.put("/credentials/{credential_id}")
async def update_credential(
    credential_id: str,
    body: VaultCredentialWrite,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    """Replace one credential; the old plaintext is never exposed to the UI."""

    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
    item = _validated(body)
    duplicate = await _find_same_credential(
        session,
        tenant_id=actor.tenant_id,
        client_key=item.client_key,
        portal=item.portal,
        credential_label=item.credential_label,
    )
    if duplicate is not None and duplicate.id != row.id:
        raise HTTPException(status_code=409, detail="Esiste già un accesso con questi dati")
    row.client_name = item.client_name
    row.client_key = item.client_key
    row.portal = item.portal
    row.portal_url = item.portal_url
    row.credential_label = item.credential_label
    row.secret_kind = item.secret_kind
    row.status = "ready"
    row.updated_by = actor.user_id
    row.updated_at = utcnow()
    encrypt_credential_fields(row, username=item.username, secret=item.secret)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="fort_knox.credential_update",
        result="ok",
        detail=f"credential_id={row.id};portal={row.portal}",
    )
    await session.commit()
    return {
        "ok": True,
        "id": row.id,
        "state": "ready",
        "username_masked": mask_username(item.username),
        "sent_to_ai": False,
    }


@router.post("/import/preview")
async def preview_import(
    actor: Annotated[Actor, Depends(get_actor)],
    file: Annotated[UploadFile, File()],
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
                portal_url=item.portal_url,
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
        row.portal_url = item.portal_url
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
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> dict:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
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
async def csv_template(
    actor: Annotated[Actor, Depends(get_actor)],
    vault_grant: Annotated[str | None, Header(alias="X-Vault-Grant")] = None,
) -> PlainTextResponse:
    _require_owner(actor)
    _require_vault_grant(actor, vault_grant)
    body = (
        "cliente;portale;link_portale;username;password;tipo_segreto;etichetta\n"
        "Esempio Cliente;webdesk;https://portale.esempio.it/login;"
        "utente@example.it;SOSTITUISCI;password;principale\n"
    )
    return PlainTextResponse(
        body,
        headers={"Content-Disposition": 'attachment; filename="kreluna-fort-knox-modello.csv"'},
    )
