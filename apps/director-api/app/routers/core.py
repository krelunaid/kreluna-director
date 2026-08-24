from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from kreluna_shared.crypto import b64d, fingerprint_device
from kreluna_shared.update import APP_VERSION, manifest_payload, sign_manifest
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import Actor, get_actor, get_policy
from app.models import AgentSlot, Device, EnrollmentCode, User
from app.security import issue_session, verify_password
from app.services.agents import compose_agent_rows
from app.services.audit import write_audit
from app.services.orchestrator import kill_all
from app.services.registry import hub, mark_offline_stale

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    password: str


class EnrollBody(BaseModel):
    enrollment_code: str
    agent_id: str
    hostname: str
    public_key: str
    fingerprint: str | None = None
    display_name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    platform: str = "linux"


@router.get("/health")
async def health() -> dict:
    from kreluna_shared.crypto import b64e, server_public_bytes

    return {
        "ok": True,
        "service": "director-api",
        "version": APP_VERSION,
        "server_pubkey": b64e(server_public_bytes(settings.director_signing_seed)),
    }


@router.get("/update/manifest")
async def update_manifest() -> dict:
    payload = manifest_payload()
    return {
        "manifest": payload,
        "signature": sign_manifest(settings.director_signing_seed, payload),
        "algorithm": "ed25519",
    }


@router.get("/ready")
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    await session.execute(select(User).limit(1))
    return {"ok": True, "service": "director-api", "ready": True}


@router.post("/auth/login")
async def login(body: LoginBody, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(settings.director_session_secret, body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    token = issue_session(
        settings.director_session_secret,
        {"user_id": user.id, "tenant_id": user.tenant_id, "role": user.role},
    )
    return {
        "token": token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "tenant_id": user.tenant_id},
    }


@router.get("/me")
async def me(actor: Annotated[Actor, Depends(get_actor)]) -> dict:
    return {
        "id": actor.user_id,
        "name": actor.name,
        "email": actor.email,
        "role": actor.role,
        "tenant_id": actor.tenant_id,
        "license_state": actor.license_state,
    }


@router.post("/enrollment/redeem")
async def redeem(body: EnrollBody, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    code = (
        await session.execute(select(EnrollmentCode).where(EnrollmentCode.code == body.enrollment_code))
    ).scalar_one_or_none()
    if code is None:
        raise HTTPException(status_code=404, detail="Codice di enrollment sconosciuto")
    try:
        raw_pub = b64d(body.public_key)
        if len(raw_pub) != 32:
            raise ValueError("bad key")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Chiave pubblica non valida") from exc

    slot = (
        await session.execute(
            select(AgentSlot).where(
                AgentSlot.tenant_id == code.tenant_id,
                AgentSlot.enrollment_code == body.enrollment_code,
            )
        )
    ).scalar_one_or_none()
    if slot is None:
        slot = (
            await session.execute(
                select(AgentSlot).where(
                    AgentSlot.tenant_id == code.tenant_id,
                    AgentSlot.role == body.agent_id,
                )
            )
        ).scalar_one_or_none()

    if slot is None and code.used:
        raise HTTPException(status_code=409, detail="Codice di enrollment già usato")
    if slot is not None and body.agent_id and body.agent_id != slot.role:
        raise HTTPException(status_code=400, detail="Questo codice è per un altro PC")

    fingerprint = body.fingerprint or fingerprint_device(body.hostname, body.agent_id)
    device = None
    if slot is not None and slot.device_id:
        device = (
            await session.execute(select(Device).where(Device.id == slot.device_id, Device.tenant_id == code.tenant_id))
        ).scalar_one_or_none()
    if device is None and slot is not None:
        device = (
            await session.execute(
                select(Device).where(Device.tenant_id == code.tenant_id, Device.agent_id == slot.role)
            )
        ).scalar_one_or_none()

    if device is None:
        device = Device(
            tenant_id=code.tenant_id,
            agent_id=slot.role if slot is not None else body.agent_id,
            hostname=body.hostname,
            display_name=(slot.display_name if slot else None) or body.display_name or body.agent_id,
            public_key=body.public_key,
            fingerprint=fingerprint,
            capabilities=json.dumps(body.capabilities),
            platform=body.platform,
            status="active",
            presence="offline",
        )
        session.add(device)
        await session.flush()
        if slot is None:
            code.used = True
            code.used_by_device_id = device.id
    else:
        device.public_key = body.public_key
        device.hostname = body.hostname
        device.capabilities = json.dumps(body.capabilities)
        device.platform = body.platform
        device.status = "active"
        device.killed = False
        device.paused = False
        if slot is not None:
            device.display_name = slot.display_name or device.display_name
            device.agent_id = slot.role

    if slot is not None:
        slot.device_id = device.id
        device.display_name = slot.display_name or device.display_name
    await write_audit(
        session,
        tenant_id=code.tenant_id,
        actor="enrollment",
        action="device.enroll",
        result="ok",
        device_id=device.id,
        detail=body.agent_id,
    )
    await session.commit()
    return {
        "device_id": device.id,
        "tenant_id": device.tenant_id,
        "agent_id": device.agent_id,
        "status": device.status,
    }


@router.get("/agents")
async def list_agents(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    await mark_offline_stale(session)
    rows = (
        await session.execute(select(Device).where(Device.tenant_id == actor.tenant_id))
    ).scalars().all()
    slots = (
        await session.execute(select(AgentSlot).where(AgentSlot.tenant_id == actor.tenant_id))
    ).scalars().all()
    await session.commit()
    return {"agents": compose_agent_rows(rows, slots)}


@router.post("/devices/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Solo il titolare può revocare un PC")
    device = (
        await session.execute(
            select(Device).where(Device.id == device_id, Device.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trovato")
    device.status = "revoked"
    device.killed = True
    await hub.send_agent(device.id, {"type": "kill", "reason": "revoked"})
    hub.drop_agent(device.id)
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="device.revoke",
        result="ok",
        device_id=device.id,
    )
    await session.commit()
    return {"ok": True, "status": "revoked"}


@router.post("/kill-switch")
async def kill_switch(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "approver", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Ruolo insufficiente per FERMA TUTTO")
    count = await kill_all(session, actor.tenant_id, actor.user_id)
    await session.commit()
    return {"ok": True, "stopped_devices": count}


@router.post("/agents/{device_id}/resume")
async def resume_agent(
    device_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "approver"}:
        raise HTTPException(status_code=403, detail="Ruolo insufficiente")
    device = (
        await session.execute(
            select(Device).where(Device.id == device_id, Device.tenant_id == actor.tenant_id)
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trovato")
    device.killed = False
    device.paused = False
    if device.id in hub.agents:
        device.presence = "online"
        await hub.send_agent(device.id, {"type": "resume"})
    await session.commit()
    return {"ok": True}


@router.get("/policy")
async def policy_view(actor: Annotated[Actor, Depends(get_actor)]) -> dict:
    engine = get_policy()
    return {
        "deny": sorted(engine._deny),
        "approval_required": sorted(engine._approval),
        "license_state": actor.license_state,
        "tenant_id": actor.tenant_id,
    }
