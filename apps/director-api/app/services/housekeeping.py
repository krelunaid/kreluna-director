"""Pulizia periodica: le foto dei PC non restano in eterno, e un PC fermo non è un errore."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Approval, Evidence, Task, as_utc, utcnow
from app.routers.agent_io import purge_expired_evidence

STOP_REASONS = ("AGENT_KILLED", "AGENT_PAUSED")


async def purge_old_evidence(session: AsyncSession) -> int:
    rows = (await session.execute(select(Evidence).where(Evidence.deleted_at.is_(None)))).scalars().all()
    removed = purge_expired_evidence(
        settings.evidence_path,
        list(rows),
        utcnow(),
        settings.evidence_retention_hours,
    )
    return len(removed)


async def heal_stopped_tasks(session: AsyncSession) -> int:
    """Un lavoro rifiutato perché il PC era fermo non è un errore dello studio."""

    rows = (
        await session.execute(select(Task).where(Task.status == "failed", Task.error.in_(STOP_REASONS)))
    ).scalars().all()
    for task in rows:
        task.status = "cancelled"
        task.error = None
    return len(rows)


OLD_CODES = {
    "CAPABILITY_NOT_ALLOWED": "Quel PC non sa fare questo lavoro: probabilmente ha un Kreluna Agent vecchio.",
    "NOT_READY": "Quel PC si era appena collegato: riprova.",
    "CAPABILITY_NOT_ALLOWED_ROLE": "Quel PC non è quello che fa questo lavoro.",
}


async def translate_old_errors(session: AsyncSession) -> int:
    """Errori vecchi scritti in gergo: li riscrive in italiano."""

    rows = (await session.execute(select(Task).where(Task.error.in_(tuple(OLD_CODES))))).scalars().all()
    for task in rows:
        task.error = OLD_CODES[task.error]
    return len(rows)


async def resolve_legacy_browser_timeouts(session: AsyncSession) -> int:
    """Archivia il vecchio errore tecnico corretto nelle versioni recenti dell'Agent."""

    rows = (
        await session.execute(
            select(Task).where(
                Task.status == "failed",
                Task.error.contains("Command '['osascript'"),
                Task.error.contains("timed out after"),
            )
        )
    ).scalars().all()
    for task in rows:
        try:
            result = json.loads(task.result_json or "{}")
        except json.JSONDecodeError:
            result = {}
        result["error_resolved"] = True
        result["resolution_code"] = "legacy_browser_timeout_fixed"
        task.result_json = json.dumps(result, ensure_ascii=False)
        task.error = (
            "Risolto dall'aggiornamento: il vecchio Agent non riusciva ad aprire "
            "Chrome entro 30 secondi. Ora usa un'apertura alternativa sicura."
        )
    return len(rows)


async def close_expired_approvals(session: AsyncSession) -> int:
    """Una conferma scaduta non deve restare in "Da approvare" per sempre."""

    now = utcnow()
    rows = (await session.execute(select(Approval).where(Approval.status == "pending"))).scalars().all()
    closed = 0
    for approval in rows:
        if as_utc(approval.expires_at) >= now:
            continue
        approval.status = "expired"
        task = (
            await session.execute(select(Task).where(Task.id == approval.task_id))
        ).scalar_one_or_none()
        if task is not None and task.status == "waiting_approval":
            task.status = "cancelled"
            task.error = "approvazione scaduta"
        closed += 1
    return closed


async def housekeeping_loop(session_factory, every_seconds: int = 3600) -> None:
    while True:
        try:
            async with session_factory() as session:
                await purge_old_evidence(session)
                await heal_stopped_tasks(session)
                await translate_old_errors(session)
                await resolve_legacy_browser_timeouts(session)
                await close_expired_approvals(session)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - la pulizia non deve mai fermare il Director
            print(f"[kreluna] pulizia rimandata: {exc}", flush=True)
        await asyncio.sleep(every_seconds)
