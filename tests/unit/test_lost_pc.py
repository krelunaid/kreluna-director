from datetime import timedelta

import pytest
from app.database import Base, SessionLocal, engine
from app.models import Device, Task, utcnow
from app.seed import DEMO_TENANT_ID, DEMO_USER_ID
from app.services.registry import mark_offline_stale, requeue_device_tasks


@pytest.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as opened:
        yield opened


async def a_pc_with_work(session, *, seen_ago_seconds: int, key: str) -> tuple[Device, Task]:
    device = Device(
        tenant_id=DEMO_TENANT_ID,
        agent_id=f"pc-prova-{key}",
        hostname=f"host-{key}",
        public_key="x",
        fingerprint=f"fp-{key}",
        capabilities='["visure_prepare"]',
        platform="macos",
        status="active",
        presence="online",
        busy=True,
        last_seen_at=utcnow() - timedelta(seconds=seen_ago_seconds),
    )
    session.add(device)
    await session.flush()
    task = Task(
        tenant_id=DEMO_TENANT_ID,
        requested_by=DEMO_USER_ID,
        goal="Preparare visura",
        capability="visure_prepare",
        args_json="{}",
        risk="medium",
        status="assigned",
        idempotency_key=f"chiave-{key}",
        assigned_device_id=device.id,
    )
    session.add(task)
    device.active_task_id = task.id
    await session.flush()
    return device, task


@pytest.mark.asyncio
async def test_work_goes_back_in_the_queue_when_the_pc_disappears(session):
    device, task = await a_pc_with_work(session, seen_ago_seconds=600, key="spento")
    await mark_offline_stale(session)
    await session.flush()
    assert device.presence == "offline"
    assert device.busy is False
    assert device.active_task_id is None
    assert task.status == "queued", "il lavoro non deve restare bloccato su un PC spento"
    assert task.assigned_device_id is None


@pytest.mark.asyncio
async def test_a_pc_that_is_still_beating_keeps_its_work(session):
    device, task = await a_pc_with_work(session, seen_ago_seconds=3, key="vivo")
    await mark_offline_stale(session)
    await session.flush()
    assert device.presence == "online"
    assert task.status == "assigned"
    assert task.assigned_device_id == device.id


@pytest.mark.asyncio
async def test_finished_work_is_not_touched(session):
    device, task = await a_pc_with_work(session, seen_ago_seconds=600, key="finito")
    task.status = "completed"
    await session.flush()
    moved = await requeue_device_tasks(session, device.id)
    assert moved == 0
    assert task.status == "completed"
