from __future__ import annotations

import json
from datetime import UTC, timedelta

from fastapi import WebSocket
from kreluna_shared.agents import preferred_role
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Device, utcnow


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


async def mark_offline_stale(session: AsyncSession) -> None:
    cutoff = utcnow() - timedelta(seconds=settings.heartbeat_timeout_seconds)
    rows = (await session.execute(select(Device))).scalars().all()
    now = utcnow()
    for device in rows:
        if device.presence == "offline":
            continue
        last = device.last_seen_at
        if last is None:
            device.presence = "offline"
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last < cutoff:
            device.presence = "offline"
            device.busy = False
            device.active_task_id = None
    _ = now


def score_agent(device: Device, capability: str, args: dict | None = None) -> int:
    caps = parse_caps(device.capabilities)
    if capability not in caps:
        return -10_000
    if device.status != "active":
        return -10_000
    if device.presence == "offline" or device.killed or device.paused:
        return -10_000
    role = preferred_role(capability, args)
    if role and device.agent_id != role:
        # Un portale vero si apre solo sul PC che fa quel lavoro.
        if capability == "portal_open":
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
