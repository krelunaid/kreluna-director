from datetime import timedelta

import pytest
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Approval, Evidence, Task, utcnow
from app.seed import DEMO_TENANT_ID, DEMO_USER_ID
from app.services.housekeeping import (
    close_expired_approvals,
    heal_stopped_tasks,
    purge_old_evidence,
)
from kreluna_shared.crypto import encrypt_bytes


@pytest.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as opened:
        yield opened


async def a_task(session, key: str, status: str = "completed", error: str | None = None) -> Task:
    task = Task(
        tenant_id=DEMO_TENANT_ID,
        requested_by=DEMO_USER_ID,
        goal=f"Lavoro {key}",
        capability="visure_prepare",
        args_json="{}",
        risk="medium",
        status=status,
        error=error,
        idempotency_key=f"pulizia-{key}",
    )
    session.add(task)
    await session.flush()
    return task


async def a_photo(session, task: Task, *, hours_old: float) -> Evidence:
    key = f"{DEMO_TENANT_ID}/{task.id}/foto-{hours_old}.bin"
    path = settings.evidence_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt_bytes(settings.director_evidence_key, b"schermata finta"))
    shot = Evidence(
        tenant_id=DEMO_TENANT_ID,
        task_id=task.id,
        device_id="pc-prova",
        kind="screenshot",
        sha256="x" * 64,
        storage_key=key,
        created_at=utcnow() - timedelta(hours=hours_old),
    )
    session.add(shot)
    await session.flush()
    return shot


@pytest.mark.asyncio
async def test_old_screenshots_are_really_deleted_from_disk(session):
    task = await a_task(session, "vecchia")
    old = await a_photo(session, task, hours_old=settings.evidence_retention_hours + 5)
    fresh = await a_photo(session, task, hours_old=1)
    old_path = settings.evidence_path / old.storage_key
    fresh_path = settings.evidence_path / fresh.storage_key
    assert old_path.exists() and fresh_path.exists()

    removed = await purge_old_evidence(session)
    await session.flush()

    assert removed >= 1
    assert not old_path.exists(), "la foto scaduta deve sparire dal disco, non solo dal database"
    assert old.deleted_at is not None
    assert fresh_path.exists(), "le foto recenti restano: sono la prova del lavoro"
    assert fresh.deleted_at is None


@pytest.mark.asyncio
async def test_purging_twice_is_harmless(session):
    task = await a_task(session, "due-volte")
    await a_photo(session, task, hours_old=settings.evidence_retention_hours + 5)
    first = await purge_old_evidence(session)
    await session.flush()
    second = await purge_old_evidence(session)
    assert first >= 1
    assert second == 0


@pytest.mark.asyncio
async def test_old_errors_get_rewritten_in_italian(session):
    from app.services.housekeeping import translate_old_errors

    gergo = await a_task(session, "gergo", status="failed", error="CAPABILITY_NOT_ALLOWED")
    chiaro = await a_task(session, "chiaro", status="failed", error="PORTALE_SCONOSCIUTO:x")
    changed = await translate_old_errors(session)
    await session.flush()
    assert changed == 1
    assert "Agent vecchio" in gergo.error
    assert chiaro.error == "PORTALE_SCONOSCIUTO:x"


@pytest.mark.asyncio
async def test_an_expired_confirmation_leaves_the_approval_list(session):
    task = await a_task(session, "scaduta", status="waiting_approval")
    still_good = await a_task(session, "buona", status="waiting_approval")
    session.add(
        Approval(
            tenant_id=DEMO_TENANT_ID,
            task_id=task.id,
            action="invoice_submit_demo",
            token_nonce="a",
            expires_at=utcnow() - timedelta(minutes=1),
        )
    )
    session.add(
        Approval(
            tenant_id=DEMO_TENANT_ID,
            task_id=still_good.id,
            action="invoice_submit_demo",
            token_nonce="b",
            expires_at=utcnow() + timedelta(minutes=30),
        )
    )
    await session.flush()

    closed = await close_expired_approvals(session)
    await session.flush()

    assert closed == 1
    assert task.status == "cancelled"
    assert task.error == "approvazione scaduta"
    assert still_good.status == "waiting_approval", "una conferma valida non si tocca"


@pytest.mark.asyncio
async def test_a_stopped_pc_stops_looking_like_an_error(session):
    stopped = await a_task(session, "fermo", status="failed", error="AGENT_KILLED")
    real = await a_task(session, "rotto", status="failed", error="PORTALE_SCONOSCIUTO:x")
    healed = await heal_stopped_tasks(session)
    await session.flush()
    assert healed == 1
    assert stopped.status == "cancelled"
    assert stopped.error is None
    assert real.status == "failed", "un errore vero resta visibile"
    assert real.error
