from __future__ import annotations

import json
from datetime import UTC, timedelta

from fastapi import WebSocket
from kreluna_shared.agents import capabilities_for_role, preferred_role
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Device, Task, utcnow


class ConnectionHub:
    def __init__(self) -> None:
        self.agents: dict[str, WebSocket] = {}
        self.dashboards: list[WebSocket] = []

    async def register_agent(self, device_id: str, ws: WebSocket) -> None:
        self.agents[device_id] = ws

    def drop_agent(self, device_id: str) -> None:
        self.agents.pop(device_id, None)

    async def send_agent(self, device_id: str, payload: dict) -> bool:
        ws = self.agents.get(device_id)
        if ws is None:
            return False
        await ws.send_json(payload)
        return True

    async def broadcast_agents(self, payload: dict) -> int:
        sent = 0
        for ws in list(self.agents.values()):
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:
                continue
        return sent

    async def broadcast_dashboard(self, payload: dict) -> None:
        stale: list[WebSocket] = []
        for ws in self.dashboards:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            if ws in self.dashboards:
                self.dashboards.remove(ws)


hub = ConnectionHub()


def parse_caps(raw: str) -> list[str]:
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def requeue_device_tasks(session: AsyncSession, device_id: str) -> int:
    """Un PC che si spegne non si porta via il lavoro: torna in coda per il prossimo."""

    orphans = (
        await session.execute(
            select(Task).where(
                Task.assigned_device_id == device_id,
                Task.status.in_(("assigned", "running")),
            )
        )
    ).scalars().all()
    for task in orphans:
        task.status = "queued"
        task.assigned_device_id = None
    return len(orphans)


async def mark_offline_stale(session: AsyncSession) -> None:
    cutoff = utcnow() - timedelta(seconds=settings.heartbeat_timeout_seconds)
    rows = (await session.execute(select(Device))).scalars().all()
    for device in rows:
        if device.presence == "offline":
            continue
        last = device.last_seen_at
        if last is None:
            device.presence = "offline"
            await requeue_device_tasks(session, device.id)
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last < cutoff:
            device.presence = "offline"
            device.busy = False
            device.active_task_id = None
            await requeue_device_tasks(session, device.id)


def allowed_capabilities(device: Device) -> list[str]:
    """Comanda la policy dello studio, non la lista che dichiara il PC.

    Un Agent vecchio dichiara i lavori di un'altra versione: il Director
    continua a mandargli il lavoro del suo ruolo, e sarà l'Agent a rifiutare
    se non lo sa fare.
    """

    by_role = capabilities_for_role(device.agent_id)
    return by_role or parse_caps(device.capabilities)


def score_agent(device: Device, capability: str, args: dict | None = None) -> int:
    if capability not in allowed_capabilities(device):
        return -10_000
    if device.status != "active":
        return -10_000
    if device.presence == "offline" or device.killed or device.paused:
        return -10_000
    role = preferred_role(capability, args)
    # Un portale vero si apre solo sul PC che fa quel lavoro.
    if capability in {"portal_open", "portal_learn"} and role and device.agent_id != role:
        return -10_000
    score = 100
    if not device.busy:
        score += 30
    if role and device.agent_id == role:
        score += 80
    plat = (device.platform or "").lower()
    if plat in {"macos", "darwin", "windows"}:
        score += 50
    elif plat == "linux":
        score -= 80
    score -= device.recent_errors * 15
    return score
