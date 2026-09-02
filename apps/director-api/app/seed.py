from __future__ import annotations

import json
import secrets
from pathlib import Path

from kreluna_shared.agents import load_agent_roles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ROOT, settings
from app.models import AgentSlot, EnrollmentCode, License, Tenant, User
from app.security import hash_password

DEMO_TENANT_ID = "11111111-1111-1111-1111-111111111111"
DEMO_USER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_TENANT_ID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_ID = "44444444-4444-4444-4444-444444444444"


async def seed_if_empty(session: AsyncSession) -> None:
    existing = (await session.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if existing is None:
        if settings.requires_unique_secrets:
            studio = Tenant(
                name=settings.director_bootstrap_tenant_name,
                slug=settings.director_bootstrap_tenant_slug,
            )
            session.add(studio)
            await session.flush()
            session.add_all(
                [
                    User(
                        tenant_id=studio.id,
                        email=settings.director_bootstrap_email.strip().lower(),
                        name=settings.director_bootstrap_name,
                        role="studio_owner",
                        password_hash=hash_password(settings.director_bootstrap_password),
                    ),
                    License(tenant_id=studio.id, state="active", plan="studio"),
                ]
            )
            await session.commit()
            await seed_agent_slots(session, studio.id)
            return
        studio = Tenant(id=DEMO_TENANT_ID, name="Studio Rossi & Associati", slug="studio-rossi")
        other = Tenant(id=OTHER_TENANT_ID, name="Studio Isolato", slug="studio-isolato")
        session.add_all([studio, other])
        session.add_all(
            [
                User(
                    id=DEMO_USER_ID,
                    tenant_id=DEMO_TENANT_ID,
                    email="andrea@studio.demo",
                    name="Andrea Gadducci",
                    role="studio_owner",
                    password_hash=hash_password("demo"),
                ),
                User(
                    id=OTHER_USER_ID,
                    tenant_id=OTHER_TENANT_ID,
                    email="altro@studio.demo",
                    name="Altro Titolare",
                    role="studio_owner",
                    password_hash=hash_password("demo"),
                ),
                License(tenant_id=DEMO_TENANT_ID, state="active", plan="studio-demo"),
                License(tenant_id=OTHER_TENANT_ID, state="active", plan="studio-demo"),
                User(
                    id="55555555-5555-5555-5555-555555555555",
                    tenant_id=DEMO_TENANT_ID,
                    email="viewer@studio.demo",
                    name="Viewer Rossi",
                    role="viewer",
                    password_hash=hash_password("demo"),
                ),
            ]
        )
        await session.commit()
    if settings.is_desktop:
        owner = await _migrate_desktop_demo_accounts(session, existing)
        await _disable_legacy_enrollment_codes(session, owner.tenant_id)
        await session.commit()
        await seed_agent_slots(session, owner.tenant_id)
        return
    if settings.is_production:
        demo_user = (
            await session.execute(
                select(User)
                .where(User.email.in_(("andrea@studio.demo", "altro@studio.demo", "viewer@studio.demo")))
                .limit(1)
            )
        ).scalar_one_or_none()
        demo_code = (
            await session.execute(
                select(EnrollmentCode).where(EnrollmentCode.code == "KRELUNA-DEV-ENROLL")
            )
        ).scalar_one_or_none()
        if demo_user is not None or demo_code is not None:
            raise RuntimeError(
                "Produzione bloccata: il database contiene account o codici demo; "
                "usa un database di produzione pulito"
            )
        await seed_agent_slots(session, existing.id)
        return
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
            if slot.enrollment_code and not slot.enrollment_code.startswith("sha256:"):
                slot.enrollment_code = ""
            continue
        if role.retired:
            continue
        session.add(
            AgentSlot(
                tenant_id=tenant_id,
                role=role.role,
                display_name=role.display_name,
                job=role.job,
                program=role.program,
                capabilities=json.dumps(role.capabilities),
                enrollment_code="",
            )
        )
    await session.commit()


async def _migrate_desktop_demo_accounts(session: AsyncSession, fallback: Tenant) -> User:
    """Preserve the local studio data while removing every known demo login."""

    email = settings.director_bootstrap_email.strip().lower()
    owner = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if owner is None:
        owner = (
            await session.execute(
                select(User)
                .where(User.email == "andrea@studio.demo")
                .limit(1)
            )
        ).scalar_one_or_none()
    if owner is None:
        owner = User(
            tenant_id=fallback.id,
            email=email,
            name=settings.director_bootstrap_name,
            role="studio_owner",
            password_hash=hash_password(settings.director_bootstrap_password),
        )
        session.add(owner)
        await session.flush()
    else:
        owner.email = email
        owner.name = settings.director_bootstrap_name
        owner.role = "studio_owner"
        owner.password_hash = hash_password(settings.director_bootstrap_password)

    demo_users = (
        await session.execute(
            select(User).where(
                User.email.in_(("andrea@studio.demo", "altro@studio.demo", "viewer@studio.demo")),
                User.id != owner.id,
            )
        )
    ).scalars().all()
    for user in demo_users:
        user.email = f"disabled-{user.id}@invalid.local"
        user.password_hash = hash_password(secrets.token_urlsafe(32))
    return owner


async def _disable_legacy_enrollment_codes(session: AsyncSession, tenant_id: str) -> None:
    codes = (
        await session.execute(select(EnrollmentCode).where(EnrollmentCode.tenant_id == tenant_id))
    ).scalars().all()
    for code in codes:
        if not code.code.startswith("sha256:"):
            code.used = True
    slots = (
        await session.execute(select(AgentSlot).where(AgentSlot.tenant_id == tenant_id))
    ).scalars().all()
    for slot in slots:
        if slot.enrollment_code and not slot.enrollment_code.startswith("sha256:"):
            slot.enrollment_code = ""
