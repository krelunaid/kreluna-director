from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_url() -> str:
    url = settings.director_database_url
    if url.startswith("sqlite+aiosqlite:///./"):
        from pathlib import Path

        from app.config import ROOT

        relative = url.removeprefix("sqlite+aiosqlite:///./")
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"
    return url


engine = create_async_engine(_engine_url(), echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
