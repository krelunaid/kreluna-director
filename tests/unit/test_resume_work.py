"""Pausa o assistenza remota: il lavoro torna in coda e Riprendi lo rimanda al PC."""

import pytest
from app.database import Base, SessionLocal, engine
from app.models import Device, Task, utcnow
from app.seed import DEMO_TENANT_ID, DEMO_USER_ID
from app.services.orchestrator import (
    recover_remote_blocked_tasks,
    release_remote_and_nudge,
    resume_device_work,
)
from app.services.registry import hub, requeue_device_tasks
from sqlalchemy import select


@pytest.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as opened:
        yield opened


class RecordingSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


async def a_pc_with_invoice(session, key: str) -> tuple[Device, Task]:
    device = Device(
        tenant_id=DEMO_TENANT_ID,
        agent_id=f"pc-riprendi-{key}",
        hostname=f"host-{key}",
        public_key="x",
        fingerprint=f"fp-riprendi-{key}",
        capabilities='["invoice_prepare_demo"]',
        platform="macos",
        status="active",
        presence="online",
        busy=True,
        last_seen_at=utcnow(),
    )
    session.add(device)
    await session.flush()
    task = Task(
        tenant_id=DEMO_TENANT_ID,
        requested_by=DEMO_USER_ID,
        goal="Preparare fattura SMART per Rossi",
        capability="invoice_prepare_demo",
        args_json="{}",
        risk="medium",
        status="assigned",
        idempotency_key=f"riprendi-{key}",
        assigned_device_id=device.id,
    )
    session.add(task)
    device.active_task_id = task.id
    await session.flush()
    others = (await session.execute(select(Device).where(Device.id != device.id))).scalars().all()
    for other in others:
        other.paused = True
        other.presence = "paused"
    leftovers = (
        await session.execute(
            select(Task).where(
                Task.id != task.id,
                Task.status.in_(("queued", "assigned", "running", "failed")),
            )
        )
    ).scalars().all()
    for leftover in leftovers:
        leftover.status = "cancelled"
        leftover.error = None
    await session.flush()
    return device, task


@pytest.mark.asyncio
async def test_pause_requeues_and_resume_dispatches_the_job(session):
    device, task = await a_pc_with_invoice(session, "pausa")
    socket = RecordingSocket()
    await hub.register_agent(device.id, device.tenant_id, socket)
    try:
        device.paused = True
        device.presence = "paused"
        device.busy = False
        device.active_task_id = None
        assert await requeue_device_tasks(session, device.id) == 1
        await session.flush()
        assert task.status == "queued"
        assert task.assigned_device_id is None

        result = await resume_device_work(session, device, DEMO_USER_ID)
        await session.flush()

        assert device.paused is False
        assert result["dispatched_tasks"] == 1
        assert task.status == "assigned"
        assert task.assigned_device_id == device.id
        assert [item["type"] for item in socket.messages] == ["resume", "task"]
        assert socket.messages[1]["task_id"] == task.id
        assert socket.messages[1]["capability"] == "invoice_prepare_demo"
    finally:
        hub.drop_agent(device.id, socket)


@pytest.mark.asyncio
async def test_resume_recovers_a_job_blocked_by_remote_assistance(session):
    device, task = await a_pc_with_invoice(session, "remoto")
    task.status = "failed"
    task.assigned_device_id = None
    task.error = "AGENT_REMOTE"
    device.busy = False
    device.active_task_id = None
    await session.flush()

    socket = RecordingSocket()
    await hub.register_agent(device.id, device.tenant_id, socket)
    try:
        assert await recover_remote_blocked_tasks(session, DEMO_TENANT_ID) == 1
        await session.flush()
        assert task.status == "queued"
        assert task.error is None

        result = await resume_device_work(session, device, DEMO_USER_ID)
        await session.flush()
        assert result["dispatched_tasks"] == 1
        assert task.status == "assigned"
        assert socket.messages[-1]["type"] == "task"
    finally:
        hub.drop_agent(device.id, socket)


@pytest.mark.asyncio
async def test_closing_remote_requeues_and_dispatches_when_pc_is_free(session):
    device, task = await a_pc_with_invoice(session, "chiudi")
    socket = RecordingSocket()
    await hub.register_agent(device.id, device.tenant_id, socket)
    try:
        nudged = await release_remote_and_nudge(session, device)
        await session.flush()
        assert nudged["requeued_tasks"] == 1
        assert nudged["dispatched_tasks"] == 1
        assert task.status == "assigned"
        assert task.assigned_device_id == device.id
        assert socket.messages[-1]["type"] == "task"
    finally:
        hub.drop_agent(device.id, socket)


@pytest.mark.asyncio
async def test_closing_remote_does_not_start_work_while_pc_is_paused(session):
    device, task = await a_pc_with_invoice(session, "ancora-fermo")
    device.paused = True
    device.presence = "paused"
    device.busy = False
    device.active_task_id = None
    assert await requeue_device_tasks(session, device.id) == 1
    await session.flush()

    socket = RecordingSocket()
    await hub.register_agent(device.id, device.tenant_id, socket)
    try:
        nudged = await release_remote_and_nudge(session, device)
        await session.flush()
        assert nudged["dispatched_tasks"] == 0
        assert task.status == "queued"
        assert socket.messages == []
    finally:
        hub.drop_agent(device.id, socket)


@pytest.mark.asyncio
async def test_stale_remote_italian_error_is_also_requeued(session):
    _device, task = await a_pc_with_invoice(session, "testo-it")
    task.status = "failed"
    task.assigned_device_id = None
    task.error = "Assistenza remota attiva: nessuna automazione consentita"
    await session.flush()
    assert await recover_remote_blocked_tasks(session, DEMO_TENANT_ID) == 1
    await session.flush()
    assert task.status == "queued"
    assert task.error is None


@pytest.mark.asyncio
async def test_finished_invoice_is_not_resent_on_resume(session):
    device, task = await a_pc_with_invoice(session, "gia-fatta")
    task.status = "completed"
    device.busy = False
    device.active_task_id = None
    await session.flush()
    socket = RecordingSocket()
    await hub.register_agent(device.id, device.tenant_id, socket)
    try:
        result = await resume_device_work(session, device, DEMO_USER_ID)
        await session.flush()
        assert result["dispatched_tasks"] == 0
        assert task.status == "completed"
        assert [item["type"] for item in socket.messages] == ["resume"]
    finally:
        hub.drop_agent(device.id, socket)
