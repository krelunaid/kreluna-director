from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Approval, Device, Task, UsedNonce, utcnow
from app.services.audit import write_audit
from app.services.registry import hub, mark_offline_stale, score_agent
from kreluna_shared.crypto import sign_grant
from kreluna_shared.models import PlannedTask
from kreluna_shared.protocol import SignedGrant


def idempotency_key(tenant_id: str, capability: str, args: dict) -> str:
    material = json.dumps({"t": tenant_id, "c": capability, "a": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


async def existing_task(session: AsyncSession, tenant_id: str, key: str) -> Task | None:
    return (
        await session.execute(select(Task).where(Task.tenant_id == tenant_id, Task.idempotency_key == key))
    ).scalar_one_or_none()


async def choose_device(session: AsyncSession, tenant_id: str, capability: str) -> Device | None:
    await mark_offline_stale(session)
    devices = (
        await session.execute(select(Device).where(Device.tenant_id == tenant_id, Device.status == "active"))
    ).scalars().all()
    ranked = sorted(devices, key=lambda device: score_agent(device, capability), reverse=True)
    if not ranked or score_agent(ranked[0], capability) < 0:
        return None
    return ranked[0]


async def enqueue_planned(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    planned: PlannedTask,
) -> Task:
    key = idempotency_key(tenant_id, planned.capability, planned.args)
    found = await existing_task(session, tenant_id, key)
    if found:
        return found
    task = Task(
        tenant_id=tenant_id,
        requested_by=user_id,
        goal=planned.goal,
        capability=planned.capability,
        args_json=json.dumps(planned.args),
        risk=planned.risk.value,
        status="waiting_approval" if planned.needs_approval else "queued",
        idempotency_key=key,
        needs_approval=planned.needs_approval,
    )
    session.add(task)
    await session.flush()
    await write_audit(
        session,
        tenant_id=tenant_id,
        actor=user_id,
        action="task.create",
        result="queued" if not planned.needs_approval else "waiting_approval",
        detail=planned.goal,
        task_id=task.id,
        capability=planned.capability,
    )
    if planned.needs_approval:
        approval = Approval(
            tenant_id=tenant_id,
            task_id=task.id,
            action=planned.capability,
            preview_json=json.dumps({"goal": planned.goal, "args": planned.args, "risk": planned.risk.value}),
            token_nonce=secrets.token_hex(16),
            expires_at=utcnow() + timedelta(minutes=30),
        )
        session.add(approval)
    return task


async def dispatch_queued(session: AsyncSession) -> list[Task]:
    tasks = (
        await session.execute(select(Task).where(Task.status == "queued"))
    ).scalars().all()
    dispatched: list[Task] = []
    for task in tasks:
        device = await choose_device(session, task.tenant_id, task.capability)
        if device is None:
            continue
        await dispatch_to_device(session, task, device)
        dispatched.append(task)
    return dispatched


async def consumed_nonces(session: AsyncSession) -> set[str]:
    rows = (await session.execute(select(UsedNonce.nonce))).scalars().all()
    return set(rows)


async def dispatch_to_device(session: AsyncSession, task: Task, device: Device) -> None:
    nonce = secrets.token_hex(16)
    grant = SignedGrant(
        tenant_id=UUID(task.tenant_id),
        device_id=UUID(device.id),
        task_id=UUID(task.id),
        capability=task.capability,
        exp=int(utcnow().timestamp()) + settings.grant_ttl_seconds,
        nonce=nonce,
    )
    token = sign_grant(settings.director_signing_seed, grant)
    session.add(UsedNonce(nonce=f"issued:{nonce}"))
    task.status = "assigned"
    task.assigned_device_id = device.id
    device.busy = True
    device.active_task_id = task.id
    device.presence = "busy"
    sent = await hub.send_agent(
        device.id,
        {
            "type": "task",
            "task_id": task.id,
            "capability": task.capability,
            "goal": task.goal,
            "args": json.loads(task.args_json),
            "grant": token,
            "timeout_seconds": 60,
        },
    )
    if not sent:
        task.status = "queued"
        task.assigned_device_id = None
        device.busy = False
        device.active_task_id = None
        device.presence = "online" if device.id in hub.agents else "offline"
        return
    await write_audit(
        session,
        tenant_id=task.tenant_id,
        actor="director",
        action="task.assign",
        result="assigned",
        device_id=device.id,
        task_id=task.id,
        capability=task.capability,
    )


async def kill_all(session: AsyncSession, tenant_id: str, actor: str) -> int:
    devices = (
        await session.execute(select(Device).where(Device.tenant_id == tenant_id, Device.status == "active"))
    ).scalars().all()
    count = 0
    for device in devices:
        device.killed = True
        device.paused = True
        device.busy = False
        device.presence = "killed" if device.id in hub.agents else "offline"
        device.active_task_id = None
        count += 1
    running = (
        await session.execute(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.status.in_(("queued", "assigned", "running")),
            )
        )
    ).scalars().all()
    for task in running:
        task.status = "cancelled"
        task.error = "kill_switch"
    await hub.broadcast_agents({"type": "kill", "reason": "FERMA TUTTO"})
    await write_audit(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="kill_switch",
        result="ok",
        detail=f"devices={count}",
    )
    await hub.broadcast_dashboard({"type": "kill", "tenant_id": tenant_id})
    return count
