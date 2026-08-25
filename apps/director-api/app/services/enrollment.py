from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentSlot, EnrollmentCode, utcnow

TOKEN_PREFIX = "KRELUNA-ENROLL-"
TOKEN_TTL_MINUTES = 20


def enrollment_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def valid_enrollment_token(token: str) -> bool:
    value = token.strip()
    return value.startswith(TOKEN_PREFIX) and 50 <= len(value) <= 100


async def issue_enrollment_token(
    session: AsyncSession,
    *,
    tenant_id: str,
    slot: AgentSlot,
) -> tuple[str, EnrollmentCode]:
    """Issue one high-entropy, tenant/role-bound token and persist only its digest."""

    previous = (
        await session.execute(
            select(EnrollmentCode).where(
                EnrollmentCode.tenant_id == tenant_id,
                EnrollmentCode.agent_id == slot.role,
                EnrollmentCode.used.is_(False),
            )
        )
    ).scalars().all()
    for item in previous:
        item.used = True

    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    digest = enrollment_digest(raw)
    record = EnrollmentCode(
        tenant_id=tenant_id,
        agent_id=slot.role,
        code=digest,
        used=False,
        expires_at=utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
    )
    session.add(record)
    slot.enrollment_code = digest
    return raw, record
