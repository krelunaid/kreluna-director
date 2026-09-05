"""Ephemeral request/reply relay. No frames or keystrokes are persisted."""
import asyncio
import secrets

from app.services.registry import hub

pending: dict[str, tuple[str, object, asyncio.Future]] = {}


async def command(device_id: str, body: dict) -> dict:
    socket = hub.agents.get(device_id)
    if socket is None:
        raise ConnectionError("Agent non collegato")
    request_id = secrets.token_hex(16)
    future = asyncio.get_running_loop().create_future()
    pending[request_id] = (device_id, socket, future)
    try:
        await socket.send_json({"type": "remote_control", "request_id": request_id, **body})
        return await asyncio.wait_for(future, 12)
    finally:
        pending.pop(request_id, None)


def reply(device_id: str, socket: object, message: dict) -> None:
    entry = pending.get(message.get("request_id"))
    if entry and entry[0] == device_id and entry[1] is socket and not entry[2].done():
        entry[2].set_result(message.get("result", {"ok": False}))
