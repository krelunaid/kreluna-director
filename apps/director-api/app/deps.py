from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from kreluna_shared.policy import PolicyEngine, load_policy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import License, User
from app.security import read_session

_policy: PolicyEngine | None = None


def get_policy() -> PolicyEngine:
    global _policy
    if _policy is None:
        _policy = load_policy(settings.director_policy_path)
    return _policy


@dataclass
class Actor:
    user_id: str
    tenant_id: str
    role: str
    name: str
    email: str
    license_state: str


async def get_actor(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Actor:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = read_session(settings.director_session_secret, token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = (
        await session.execute(
            select(User).where(User.id == claims["user_id"], User.tenant_id == claims["tenant_id"])
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Utente non trovato")
    license_row = (
        await session.execute(select(License).where(License.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    return Actor(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        name=user.name,
        email=user.email,
        license_state=license_row.state if license_row else "suspended",
    )


def require_roles(*roles: str):
    async def checker(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if actor.role not in roles:
            raise HTTPException(status_code=403, detail="Ruolo insufficiente")
        return actor

    return checker
