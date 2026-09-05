from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from uuid import UUID

from kreluna_shared.crypto import sign_grant
from kreluna_shared.models import PlannedTask
from kreluna_shared.protocol import SignedGrant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Approval, Device, Task, UsedNonce, utcnow
from app.services.audit import write_audit
from app.services.registry import hub, mark_offline_stale, requeue_device_tasks, score_agent

LIVE_STATUSES = ("queued", "assigned", "running", "waiting_approval")
# Pause, stop, or remote assistance: the job is intact and must stay queued.
INTERRUPT_REQUEUE_ERRORS = ("AGENT_KILLED", "AGENT_PAUSED", "AGENT_REMOTE")
REMOTE_BLOCK_ERRORS = (
    "AGENT_REMOTE",
    "Assistenza remota attiva: nessuna automazione consentita",
)


def idempotency_key(tenant_id: str, capability: str, args: dict) -> str:
    material = json.dumps({"t": tenant_id, "c": capability, "a": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


async def same_request_tasks(session: AsyncSession, tenant_id: str, base_key: str) -> list[Task]:
    rows = (
        await session.execute(
            select(Task).where(Task.tenant_id == tenant_id, Task.idempotency_key.like(f"{base_key}%"))
        )
    ).scalars().all()
    return list(rows)


async def existing_task(session: AsyncSession, tenant_id: str, key: str) -> Task | None:
    """Solo un lavoro ancora vivo blocca un doppione. Uno annullato o finito si può richiedere."""

    for task in await same_request_tasks(session, tenant_id, key):
        if task.status in LIVE_STATUSES:
            return task
    return None


async def choose_device(
    session: AsyncSession,
    tenant_id: str,
    capability: str,
    args: dict | None = None,
) -> Device | None:
    await mark_offline_stale(session)
    devices = (
        await session.execute(select(Device).where(Device.tenant_id == tenant_id, Device.status == "active"))
    ).scalars().all()
    ranked = sorted(devices, key=lambda device: score_agent(device, capability, args), reverse=True)
    if not ranked or score_agent(ranked[0], capability, args) < 0:
        return None
    return ranked[0]


async def enqueue_planned(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    planned: PlannedTask,
) -> Task:
    base_key = idempotency_key(tenant_id, planned.capability, planned.args)
    previous = await same_request_tasks(session, tenant_id, base_key)
    for candidate in previous:
        if candidate.status in LIVE_STATUSES:
            return candidate
    key = base_key if not previous else f"{base_key}:{len(previous) + 1}"
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
        device = await choose_device(session, task.tenant_id, task.capability, json.loads(task.args_json))
        if device is None:
            continue
        await dispatch_to_device(session, task, device)
        dispatched.append(task)
    return dispatched


async def recover_remote_blocked_tasks(session: AsyncSession, tenant_id: str) -> int:
    """Un lavoro rifiutato perché era aperta l'assistenza remota torna in coda."""

    rows = (
        await session.execute(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.status == "failed",
                Task.error.in_(REMOTE_BLOCK_ERRORS),
            )
        )
    ).scalars().all()
    for task in rows:
        task.status = "queued"
        task.assigned_device_id = None
        task.error = None
    return len(rows)


async def resume_device_work(session: AsyncSession, device: Device, actor: str) -> dict:
    """Riattiva il PC e rimanda subito i lavori in coda. Non riprende un modulo a metà."""

    device.killed = False
    device.paused = False
    if device.id in hub.agents:
        device.presence = "online"
        device.last_seen_at = utcnow()
        await hub.send_agent(device.id, {"type": "resume"})
    elif device.presence in {"paused", "killed"}:
        device.presence = "offline"
    recovered = await recover_remote_blocked_tasks(session, device.tenant_id)
    dispatched = await dispatch_queued(session)
    await write_audit(
        session,
        tenant_id=device.tenant_id,
        actor=actor,
        action="agent.resume_work",
        result="ok",
        device_id=device.id,
        detail=json.dumps({"dispatched_tasks": len(dispatched), "requeued_blocked": recovered}),
    )
    return {
        "ok": True,
        "dispatched_tasks": len(dispatched),
        "requeued_blocked": recovered,
    }


async def release_remote_and_nudge(session: AsyncSession, device: Device) -> dict:
    """Dopo Chiudi: il PC è di nuovo libero. Rimette in coda ciò che era bloccato e lo rimanda."""

    recovered = await recover_remote_blocked_tasks(session, device.tenant_id)
    requeued = 0
    if not device.paused and not device.killed:
        requeued = await requeue_device_tasks(session, device.id)
        dispatched = await dispatch_queued(session)
    else:
        dispatched = []
    return {
        "requeued_blocked": recovered,
        "requeued_tasks": requeued,
        "dispatched_tasks": len(dispatched),
    }


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
    await hub.broadcast_agents(tenant_id, {"type": "kill", "reason": "FERMA TUTTO"})
    await write_audit(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="kill_switch",
        result="ok",
        detail=f"devices={count}",
    )
    await hub.broadcast_dashboard(tenant_id, {"type": "kill", "tenant_id": tenant_id})
    return count
