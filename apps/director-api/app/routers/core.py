from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
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
from app.security import hash_password, issue_session, password_needs_rehash, verify_password
from app.services.agents import compose_agent_rows
from app.services.ai import check_ai_health, save_selected_provider, selected_provider
from app.services.audit import write_audit
from app.services.orchestrator import kill_all
from app.services.registry import hub, mark_offline_stale, requeue_device_tasks
from app.services.updates import latest_update_status

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


class AIProviderBody(BaseModel):
    provider: str


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


@router.get("/update/status")
async def update_status() -> dict:
    return await latest_update_status()


def _schedule_process_exit(delay: float = 1.5) -> None:
    def stop() -> None:
        os._exit(0)

    timer = threading.Timer(delay, stop)
    timer.daemon = True
    timer.start()


@router.post("/update/install")
async def install_update(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Solo il titolare può installare aggiornamenti")
    if sys.platform != "darwin" or os.environ.get("KRELUNA_DESKTOP_APP") != "1":
        raise HTTPException(
            status_code=409,
            detail="L'installazione automatica è disponibile nell'app Kreluna per Mac.",
        )

    from kreluna_shared.macos_update import MacUpdateError, launch_macos_update, stage_macos_update

    status = await latest_update_status(force=True)
    app_bundle = Path(os.environ.get("KRELUNA_APP_BUNDLE") or "")
    support_dir = Path(
        os.environ.get("KRELUNA_SUPPORT_DIR")
        or (Path.home() / "Library" / "Application Support" / "KrelunaDirector")
    )
    try:
        staged = await asyncio.to_thread(
            stage_macos_update,
            status,
            current_app=app_bundle,
            support_dir=support_dir,
        )
    except MacUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Non riesco a preparare l'aggiornamento. Riprova tra poco.",
        ) from exc

    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="software.update.install",
        result="started",
        detail=staged.version,
    )
    await session.commit()
    try:
        launch_macos_update(staged, parent_pid=os.getpid())
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Aggiornamento verificato, ma il riavvio non può ancora partire.",
        ) from exc
    _schedule_process_exit()
    return {
        "ok": True,
        "state": "restarting",
        "version": staged.version,
    }


@router.get("/ready")
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    await session.execute(select(User).limit(1))
    return {"ok": True, "service": "director-api", "ready": True}


@router.get("/ai/providers")
async def ai_providers(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    current = await selected_provider(session, actor.tenant_id)
    providers = []
    for name in ("grok", "ollama", "openai"):
        config = settings.ai_provider_config(name)
        providers.append(
            {
                "provider": name,
                "label": config.label,
                "model": config.model,
                "configured": config.configured,
            }
        )
    return {"selected": current, "providers": providers}


@router.get("/ai/health")
async def ai_health(
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    current = await selected_provider(session, actor.tenant_id)
    return await check_ai_health(settings.ai_provider_config(current), force=True)


@router.post("/ai/provider")
async def choose_ai_provider(
    body: AIProviderBody,
    actor: Annotated[Actor, Depends(get_actor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if actor.role not in {"studio_owner", "platform_admin"}:
        raise HTTPException(status_code=403, detail="Solo il titolare può cambiare provider IA")
    try:
        chosen = await save_selected_provider(
            session,
            tenant_id=actor.tenant_id,
            provider=body.provider,
            actor_id=actor.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="ai.provider.select",
        result="ok",
        detail=chosen,
    )
    await session.commit()
    return await check_ai_health(settings.ai_provider_config(chosen), force=True)


@router.post("/auth/login")
async def login(body: LoginBody, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(
        body.password,
        user.password_hash,
        legacy_secret=settings.director_session_secret,
    ):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        await session.commit()
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


@router.post("/agents/{device_id}/pause")
async def pause_agent(
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
    device.paused = True
    device.presence = "paused"
    device.busy = False
    device.active_task_id = None
    requeued = await requeue_device_tasks(session, device.id)
    if device.id in hub.agents:
        await hub.send_agent(device.id, {"type": "pause"})
    await write_audit(
        session,
        tenant_id=actor.tenant_id,
        actor=actor.user_id,
        action="agent.pause",
        result="ok",
        device_id=device.id,
        detail=json.dumps({"requeued_tasks": requeued}),
    )
    await session.commit()
    return {"ok": True, "requeued_tasks": requeued}


@router.get("/policy")
async def policy_view(actor: Annotated[Actor, Depends(get_actor)]) -> dict:
    engine = get_policy()
    return {
        "deny": sorted(engine._deny),
        "approval_required": sorted(engine._approval),
        "license_state": actor.license_state,
        "tenant_id": actor.tenant_id,
    }
