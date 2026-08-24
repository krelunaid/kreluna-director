from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Device, utcnow
from app.services.orchestrator import dispatch_queued
from app.services.registry import hub, parse_caps, requeue_device_tasks

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_socket(ws: WebSocket) -> None:
    await ws.accept()
    device_id: str | None = None
    try:
        while True:
            message = await ws.receive_json()
            msg_type = message.get("type")
            if msg_type == "hello":
                async with SessionLocal() as session:
                    device = (
                        await session.execute(select(Device).where(Device.id == message.get("device_id")))
                    ).scalar_one_or_none()
                    if device is None or device.status != "active":
                        await ws.send_json({"type": "error", "error": "DEVICE_REVOKED_OR_UNKNOWN"})
                        await ws.close()
                        return
                    if device.killed:
                        await ws.send_json({"type": "kill", "reason": "still_killed"})
                    device_id = device.id
                    device.presence = "killed" if device.killed else "online"
                    device.hostname = message.get("hostname") or device.hostname
                    device.capabilities = json.dumps(message.get("capabilities") or parse_caps(device.capabilities))
                    device.platform = message.get("platform") or device.platform
                    device.last_seen_at = utcnow()
                    device.display_name = message.get("display_name") or device.display_name
                    await session.commit()
                    await hub.register_agent(device.id, ws)
                    await ws.send_json({"type": "welcome", "device_id": device.id})
                    await dispatch_queued(session)
                    await session.commit()
                    await hub.broadcast_dashboard({"type": "agent", "device_id": device.id, "presence": device.presence})
            elif msg_type == "heartbeat" and device_id:
                async with SessionLocal() as session:
                    device = (await session.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                    if device is None or device.status != "active":
                        await ws.send_json({"type": "kill", "reason": "revoked"})
                        break
                    device.last_seen_at = utcnow()
                    device.busy = bool(message.get("busy"))
                    device.active_task_id = message.get("active_task_id")
                    if device.killed:
                        device.presence = "killed"
                        await ws.send_json({"type": "kill", "reason": "killed"})
                    elif device.paused:
                        device.presence = "paused"
                    else:
                        device.presence = "busy" if device.busy else "online"
                    await session.commit()
            elif msg_type == "killed" and device_id:
                async with SessionLocal() as session:
                    device = (await session.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                    if device:
                        device.killed = True
                        device.busy = False
                        device.presence = "killed"
                        await session.commit()
    except WebSocketDisconnect:
        pass
    finally:
        if device_id:
            hub.drop_agent(device_id)
            async with SessionLocal() as session:
                device = (await session.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                if device:
                    device.presence = "offline"
                    device.busy = False
                    device.active_task_id = None
                    await requeue_device_tasks(session, device.id)
                    await session.commit()
            await hub.broadcast_dashboard({"type": "agent", "device_id": device_id, "presence": "offline"})


@router.websocket("/ws/dashboard")
async def dashboard_socket(ws: WebSocket) -> None:
    await ws.accept()
    hub.dashboards.append(ws)
    try:
        await ws.send_json({"type": "hello", "service": "director"})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in hub.dashboards:
            hub.dashboards.remove(ws)
