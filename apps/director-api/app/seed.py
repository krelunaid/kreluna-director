from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ROOT, settings
from app.models import AgentSlot, EnrollmentCode, License, Tenant, User
from app.security import hash_password
from kreluna_shared.agents import load_agent_roles

DEMO_TENANT_ID = "11111111-1111-1111-1111-111111111111"
DEMO_USER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_TENANT_ID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_ID = "44444444-4444-4444-4444-444444444444"


async def seed_if_empty(session: AsyncSession) -> None:
    existing = (await session.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if existing is None:
        studio = Tenant(id=DEMO_TENANT_ID, name="Studio Rossi & Associati", slug="studio-rossi")
        other = Tenant(id=OTHER_TENANT_ID, name="Studio Isolato", slug="studio-isolato")
        session.add_all([studio, other])
        session.add_all(
            [
                User(
                    id=DEMO_USER_ID,
                    tenant_id=DEMO_TENANT_ID,
                    email="andrea@studio.demo",
                    name="Andrea Rossi",
                    role="studio_owner",
                    password_hash=hash_password(settings.director_session_secret, "demo"),
                ),
                User(
                    id=OTHER_USER_ID,
                    tenant_id=OTHER_TENANT_ID,
                    email="altro@studio.demo",
                    name="Altro Titolare",
                    role="studio_owner",
                    password_hash=hash_password(settings.director_session_secret, "demo"),
                ),
                License(tenant_id=DEMO_TENANT_ID, state="active", plan="studio-demo"),
                License(tenant_id=OTHER_TENANT_ID, state="active", plan="studio-demo"),
                EnrollmentCode(tenant_id=DEMO_TENANT_ID, code=settings.kreluna_enrollment_code, used=False),
                User(
                    id="55555555-5555-5555-5555-555555555555",
                    tenant_id=DEMO_TENANT_ID,
                    email="viewer@studio.demo",
                    name="Viewer Rossi",
                    role="viewer",
                    password_hash=hash_password(settings.director_session_secret, "demo"),
                ),
            ]
        )
        await session.commit()
    await seed_agent_slots(session, DEMO_TENANT_ID)


async def seed_agent_slots(session: AsyncSession, tenant_id: str) -> None:
    roles = load_agent_roles(Path(ROOT) / "policies" / "agents.yaml")
    existing = {
        row.role
        for row in (
            await session.execute(select(AgentSlot).where(AgentSlot.tenant_id == tenant_id))
        ).scalars()
    }
    for role in roles:
        if role.role in existing:
            slot = (
                await session.execute(
                    select(AgentSlot).where(AgentSlot.tenant_id == tenant_id, AgentSlot.role == role.role)
                )
            ).scalar_one()
            slot.job = role.job
            slot.program = role.program
            slot.display_name = role.display_name
            slot.capabilities = json.dumps(role.capabilities)
            continue
        if role.retired:
            continue
        code = f"KRELUNA-{role.role.upper().replace('_', '-')}"
        already = (
            await session.execute(select(EnrollmentCode).where(EnrollmentCode.code == code))
        ).scalar_one_or_none()
        if already is None:
            session.add(EnrollmentCode(tenant_id=tenant_id, code=code, used=False))
        session.add(
            AgentSlot(
                tenant_id=tenant_id,
                role=role.role,
                display_name=role.display_name,
                job=role.job,
                program=role.program,
                capabilities=json.dumps(role.capabilities),
                enrollment_code=code,
            )
        )
    await session.commit()
