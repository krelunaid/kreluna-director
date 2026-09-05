from __future__ import annotations

import base64
import binascii
import json
import secrets
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from kreluna_shared.crypto import agent_challenge_payload, b64d, verify_bytes
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Device, User, utcnow
from app.security import read_session
from app.services.orchestrator import dispatch_queued
from app.services.registry import hub, parse_caps, requeue_device_tasks

router = APIRouter()
CHALLENGE_TTL_SECONDS = 20


def _bearer_from_websocket(ws: WebSocket) -> str:
    authorization = ws.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    for protocol in ws.headers.get("sec-websocket-protocol", "").split(","):
        value = protocol.strip()
        if not value.startswith("kreluna-session."):
            continue
        encoded = value.removeprefix("kreluna-session.")
        try:
            padding = "=" * (-len(encoded) % 4)
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return ""
    return ws.query_params.get("token", "").strip()


async def _dashboard_tenant(ws: WebSocket) -> str | None:
    token = _bearer_from_websocket(ws)
    if not token:
        return None
    try:
        claims = read_session(settings.director_session_secret, token)
    except (PermissionError, KeyError, TypeError, ValueError):
        return None
    async with SessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(
                    User.id == claims.get("user_id"),
                    User.tenant_id == claims.get("tenant_id"),
                )
            )
        ).scalar_one_or_none()
    return user.tenant_id if user is not None else None


@router.websocket("/ws/agent")
async def agent_socket(ws: WebSocket) -> None:
    await ws.accept()
    challenge = secrets.token_urlsafe(32)
    challenge_expires = int(time.time()) + CHALLENGE_TTL_SECONDS
    await ws.send_json(
        {
            "type": "challenge",
            "challenge": challenge,
            "expires_at": challenge_expires,
        }
    )
    device_id: str | None = None
    tenant_id: str | None = None
    try:
        while True:
            message = await ws.receive_json()
            msg_type = message.get("type")
            if device_id is None:
                if msg_type != "hello" or int(time.time()) > challenge_expires:
                    await ws.send_json({"type": "error", "error": "AGENT_AUTH_REQUIRED"})
                    await ws.close(code=4401)
                    return
                async with SessionLocal() as session:
                    device = (
                        await session.execute(
                            select(Device).where(Device.id == message.get("device_id"))
                        )
                    ).scalar_one_or_none()
                    if device is None or device.status != "active":
                        await ws.send_json(
                            {"type": "error", "error": "DEVICE_REVOKED_OR_UNKNOWN"}
                        )
                        await ws.close(code=4401)
                        return
                    claimed_agent = str(message.get("agent_id") or "")
                    signature = str(message.get("signature") or "")
                    if (
                        message.get("challenge") != challenge
                        or claimed_agent != device.agent_id
                        or not signature
                    ):
                        await ws.send_json({"type": "error", "error": "AGENT_AUTH_INVALID"})
                        await ws.close(code=4401)
                        return
                    try:
                        authenticated = verify_bytes(
                            b64d(device.public_key),
                            agent_challenge_payload(device.id, device.agent_id, challenge),
                            b64d(signature),
                        )
                    except (ValueError, TypeError, binascii.Error):
                        authenticated = False
                    if not authenticated:
                        await ws.send_json({"type": "error", "error": "AGENT_AUTH_INVALID"})
                        await ws.close(code=4401)
                        return
                    if device.killed:
                        await ws.send_json({"type": "kill", "reason": "still_killed"})
                    device_id = device.id
                    tenant_id = device.tenant_id
                    device.presence = "killed" if device.killed else "online"
                    device.hostname = message.get("hostname") or device.hostname
                    device.capabilities = json.dumps(
                        message.get("capabilities") or parse_caps(device.capabilities)
                    )
                    device.platform = message.get("platform") or device.platform
                    device.last_seen_at = utcnow()
                    device.display_name = message.get("display_name") or device.display_name
                    await session.commit()
                    await hub.register_agent(device.id, device.tenant_id, ws)
                    await ws.send_json({"type": "welcome", "device_id": device.id})
                    await dispatch_queued(session)
                    await session.commit()
                    await hub.broadcast_dashboard(
                        device.tenant_id,
                        {
                            "type": "agent",
                            "device_id": device.id,
                            "presence": device.presence,
                        },
                    )
                continue
            if msg_type == "remote_control_reply":
                from app.services.remote_control import reply
                reply(device_id, ws, message)
            elif msg_type == "heartbeat":
                async with SessionLocal() as session:
                    device = (
                        await session.execute(select(Device).where(Device.id == device_id))
                    ).scalar_one_or_none()
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
            elif msg_type == "killed":
                async with SessionLocal() as session:
                    device = (
                        await session.execute(select(Device).where(Device.id == device_id))
                    ).scalar_one_or_none()
                    if device:
                        device.killed = True
                        device.busy = False
                        device.presence = "killed"
                        await session.commit()
    except WebSocketDisconnect:
        pass
    finally:
        if device_id and hub.drop_agent(device_id, ws):
            async with SessionLocal() as session:
                device = (
                    await session.execute(select(Device).where(Device.id == device_id))
                ).scalar_one_or_none()
                if device:
                    device.presence = "offline"
                    device.busy = False
                    device.active_task_id = None
                    await requeue_device_tasks(session, device.id)
                    await session.commit()
            if tenant_id:
                await hub.broadcast_dashboard(
                    tenant_id,
                    {"type": "agent", "device_id": device_id, "presence": "offline"},
                )


@router.websocket("/ws/dashboard")
async def dashboard_socket(ws: WebSocket) -> None:
    tenant_id = await _dashboard_tenant(ws)
    if tenant_id is None:
        await ws.close(code=4401)
        return
    offered = {
        item.strip() for item in ws.headers.get("sec-websocket-protocol", "").split(",")
    }
    subprotocol = "kreluna-dashboard" if "kreluna-dashboard" in offered else None
    await ws.accept(subprotocol=subprotocol)
    hub.register_dashboard(tenant_id, ws)
    try:
        await ws.send_json({"type": "hello", "service": "director"})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.drop_dashboard(ws)
