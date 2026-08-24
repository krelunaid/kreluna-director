from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent
from kreluna_shared.crypto import redact_text


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    result: str,
    detail: str = "",
    device_id: str | None = None,
    task_id: str | None = None,
    capability: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        result=result,
        detail=redact_text(detail),
        device_id=device_id,
        task_id=task_id,
        capability=capability,
    )
    session.add(event)
    await session.flush()
    return event
