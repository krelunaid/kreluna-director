from typing import Annotated, Literal
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.deps import Actor, get_actor
from app.models import Device
from app.services.remote_control import command

router = APIRouter()


class RemoteCommand(BaseModel):
    action: Literal["start", "frame", "control", "click", "scroll", "text", "key", "close"]
    delta_y: int = Field(default=0, ge=-800, le=800)
    session_id: str = Field(default="", max_length=64)
    frame_id: str = Field(default="", max_length=64)
    x: float = Field(default=0, ge=0, lt=1)
    y: float = Field(default=0, ge=0, lt=1)
    text: str = Field(default="", max_length=256)
    key: Literal["", "Enter", "Tab", "Backspace", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"] = ""


@router.post("/agents/{device_id}/remote-control")
async def remote_control(device_id: str, body: RemoteCommand, response: Response,
                         actor: Annotated[Actor, Depends(get_actor)],
                         session: Annotated[AsyncSession, Depends(get_session)]):
    response.headers["Cache-Control"] = "no-store"
    if actor.role not in {"studio_owner", "approver"} or actor.license_state != "active":
        raise HTTPException(403, "Assistenza remota non autorizzata")
    device = (await session.execute(select(Device).where(
        Device.id == device_id, Device.tenant_id == actor.tenant_id,
        Device.status == "active"))).scalar_one_or_none()
    if device is None:
        raise HTTPException(404, "PC non disponibile")
    if device.killed:
        raise HTTPException(409, "Agent fermato: assistenza remota disabilitata")
    try:
        result = await command(device_id, {**body.model_dump(), "owner": actor.user_id})
    except (TimeoutError, asyncio.TimeoutError, ConnectionError, RuntimeError):
        raise HTTPException(503, "Agent non raggiungibile o da aggiornare") from None
    if not result.get("ok"):
        raise HTTPException(409, result.get("error", "Comando non eseguito"))
    return result
