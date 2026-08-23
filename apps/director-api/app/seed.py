from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import EnrollmentCode, License, Tenant, User
from app.security import hash_password

DEMO_TENANT_ID = "11111111-1111-1111-1111-111111111111"
DEMO_USER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_TENANT_ID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_ID = "44444444-4444-4444-4444-444444444444"


async def seed_if_empty(session: AsyncSession) -> None:
    existing = (await session.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if existing:
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
        ]
    )
    await session.commit()
