from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def migrate_compatible_schema(connection) -> None:
    """Aggiunge colonne compatibili senza cancellare le bozze già presenti."""

    from sqlalchemy import inspect

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "invoice_drafts" in tables:
        columns = {item["name"] for item in inspector.get_columns("invoice_drafts")}
        if "account_name" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE invoice_drafts ADD COLUMN account_name VARCHAR(200) NOT NULL DEFAULT ''"
            )
        if "vat_note" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE invoice_drafts ADD COLUMN vat_note VARCHAR(300) NOT NULL DEFAULT ''"
            )
    if "enrollment_codes" in tables:
        columns = {item["name"] for item in inspector.get_columns("enrollment_codes")}
        if "agent_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE enrollment_codes ADD COLUMN agent_id VARCHAR(80) NOT NULL DEFAULT ''"
            )
        if "expires_at" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE enrollment_codes ADD COLUMN expires_at DATETIME NULL"
            )


def _engine_url() -> str:
    url = settings.director_database_url
    if url.startswith("sqlite+aiosqlite:///./"):

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
