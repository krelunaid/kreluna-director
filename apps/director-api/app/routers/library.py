from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from kreluna_shared.crypto import decrypt_bytes, encrypt_bytes
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, get_actor
from app.models import WorkspaceDocument, utcnow
from app.services.audit import write_audit

router = APIRouter(prefix="/library", tags=["library"])

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_CATEGORIES = {"contract", "document"}
TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
    "text/xml",
}
ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".pdf", ".png", ".jpg", ".jpeg",
    ".webp", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods",
}


class TextDocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["contract", "document"]
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=MAX_TEXT_BYTES)
    notes: str = Field(default="", max_length=4000)


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    notes: str = Field(default="", max_length=4000)
    content: str | None = Field(default=None, max_length=MAX_TEXT_BYTES)


def _require_write(actor: Actor) -> None:
    if actor.role == "viewer":
        raise HTTPException(status_code=403, detail="Il visore può solo leggere")


def _require_content_access(actor: Actor) -> None:
    if actor.role == "platform_admin":
        raise HTTPException(status_code=403, detail="Il platform admin non vede i documenti dello studio")


def _document_dir() -> Path:
    path = settings.evidence_path.parent / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(value: str, fallback: str = "documento") -> str:
    name = Path(value).name.strip().replace("\x00", "")
    name = re.sub(r"[^\w.()\- ]+", "_", name, flags=re.UNICODE).strip(" .")
    return (name or fallback)[:240]


def _category(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoria documento non valida")
    return normalized


def _textual(content_type: str, filename: str) -> bool:
    return content_type.split(";", 1)[0].lower() in TEXT_TYPES or Path(filename).suffix.lower() in {
        ".txt", ".md", ".csv", ".json", ".xml",
    }


def _out(row: WorkspaceDocument) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "notes": row.notes,
        "editable": _textual(row.content_type, row.filename),
        "previewable": _textual(row.content_type, row.filename)
        or row.content_type.startswith("image/")
        or row.content_type == "application/pdf",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _find(session: AsyncSession, actor: Actor, document_id: str) -> WorkspaceDocument:
    row = (
        await session.execute(
            select(WorkspaceDocument).where(
                WorkspaceDocument.id == document_id,
                WorkspaceDocument.tenant_id == actor.tenant_id,
                WorkspaceDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    return row


def _storage_path(row: WorkspaceDocument) -> Path:
    root = _document_dir().resolve()
    path = (root / row.storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Percorso documento non valido") from exc
    return path


def _save_bytes(data: bytes) -> tuple[str, str]:
    storage_key = f"{uuid4().hex}.bin"
    destination = _document_dir() / storage_key
    destination.write_bytes(encrypt_bytes(settings.director_evidence_key, data))
    return storage_key, hashlib.sha256(data).hexdigest()


def _read_bytes(row: WorkspaceDocument) -> bytes:
    path = _storage_path(row)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File documento assente")
    try:
        return decrypt_bytes(settings.director_evidence_key, path.read_bytes())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Documento cifrato non leggibile") from exc


@router.get("")
async def list_documents(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    category: Literal["contract", "document"] | None = None,
) -> dict:
    _require_content_access(actor)
    query = select(WorkspaceDocument).where(
        WorkspaceDocument.tenant_id == actor.tenant_id,
        WorkspaceDocument.deleted_at.is_(None),
    )
    if category:
        query = query.where(WorkspaceDocument.category == category)
    rows = (await session.execute(query.order_by(WorkspaceDocument.updated_at.desc()))).scalars().all()
    return {"documents": [_out(row) for row in rows], "count": len(rows)}


@router.post("/text", status_code=201)
async def create_text_document(
    body: TextDocumentWrite,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_content_access(actor)
    _require_write(actor)
    raw = body.content.encode("utf-8")
    storage_key, digest = _save_bytes(raw)
    suffix = "contratto" if body.category == "contract" else "documento"
    row = WorkspaceDocument(
        tenant_id=actor.tenant_id,
        category=body.category,
        title=body.title.strip(),
        filename=_safe_filename(f"{body.title.strip() or suffix}.txt", f"{suffix}.txt"),
        content_type="text/plain; charset=utf-8",
        size_bytes=len(raw),
        sha256=digest,
        storage_key=storage_key,
        notes=body.notes.strip(),
        created_by=actor.user_id,
    )
    session.add(row)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="library.document.create",
        result="ok",
        detail=f"category={row.category};id={row.id}",
    )
    await session.commit()
    return _out(row)


@router.post("/upload", status_code=201)
async def upload_document(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    category: Annotated[str, Form()],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    notes: Annotated[str, Form()] = "",
) -> dict:
    _require_content_access(actor)
    _require_write(actor)
    category = _category(category)
    cleaned_filename = _safe_filename(file.filename or "documento")
    extension = Path(cleaned_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Tipo di file non supportato")
    raw = await file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Il file supera 20 MB")
    if not raw:
        raise HTTPException(status_code=400, detail="Il file è vuoto")
    content_type = (file.content_type or mimetypes.guess_type(cleaned_filename)[0] or "application/octet-stream").lower()
    storage_key, digest = _save_bytes(raw)
    row = WorkspaceDocument(
        tenant_id=actor.tenant_id,
        category=category,
        title=(title.strip() or Path(cleaned_filename).stem)[:240],
        filename=cleaned_filename,
        content_type=content_type[:160],
        size_bytes=len(raw),
        sha256=digest,
        storage_key=storage_key,
        notes=notes.strip()[:4000],
        created_by=actor.user_id,
    )
    session.add(row)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="library.document.upload",
        result="ok",
        detail=f"category={row.category};id={row.id};size={row.size_bytes}",
    )
    await session.commit()
    return _out(row)


@router.get("/{document_id}/text")
async def read_document_text(
    document_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_content_access(actor)
    row = await _find(session, actor, document_id)
    if not _textual(row.content_type, row.filename):
        raise HTTPException(status_code=409, detail="Questo formato non è modificabile dentro Kreluna")
    try:
        content = _read_bytes(row).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=409, detail="Il testo non è in formato UTF-8") from exc
    return {**_out(row), "content": content}


@router.put("/{document_id}")
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_content_access(actor)
    _require_write(actor)
    row = await _find(session, actor, document_id)
    row.title = body.title.strip()
    row.notes = body.notes.strip()
    if body.content is not None:
        if not _textual(row.content_type, row.filename):
            raise HTTPException(status_code=409, detail="Questo formato non è modificabile dentro Kreluna")
        raw = body.content.encode("utf-8")
        old_path = _storage_path(row)
        old_path.write_bytes(encrypt_bytes(settings.director_evidence_key, raw))
        row.size_bytes = len(raw)
        row.sha256 = hashlib.sha256(raw).hexdigest()
    row.updated_at = utcnow()
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="library.document.update",
        result="ok",
        detail=f"category={row.category};id={row.id}",
    )
    await session.commit()
    return _out(row)


@router.get("/{document_id}/file")
async def document_file(
    document_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    disposition: Literal["inline", "attachment"] = "attachment",
) -> Response:
    _require_content_access(actor)
    row = await _find(session, actor, document_id)
    filename = quote(row.filename, safe="")
    return Response(
        content=_read_bytes(row),
        media_type=row.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    _require_content_access(actor)
    _require_write(actor)
    row = await _find(session, actor, document_id)
    row.deleted_at = utcnow()
    row.updated_at = row.deleted_at
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="library.document.delete",
        result="ok",
        detail=f"category={row.category};id={row.id}",
    )
    await session.commit()
    path = _storage_path(row)
    if path.exists():
        path.unlink()
    return {"ok": True, "deleted": True}
