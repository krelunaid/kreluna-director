import pytest
from app.database import Base, SessionLocal, engine
from app.models import Task
from app.seed import DEMO_TENANT_ID, DEMO_USER_ID
from app.services.orchestrator import enqueue_planned
from kreluna_shared.models import PlannedTask, Risk
from sqlalchemy import select


def visura(client: str = "Andrea Gadducci") -> PlannedTask:
    return PlannedTask(
        goal=f"Preparare visura per {client}",
        capability="visure_prepare",
        args={"client_name": client},
        risk=Risk.MEDIUM,
    )


@pytest.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as opened:
        yield opened


async def live_count(session, capability: str) -> int:
    rows = (await session.execute(select(Task).where(Task.capability == capability))).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_asking_twice_while_waiting_does_not_duplicate(session):
    first = await enqueue_planned(session, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, planned=visura())
    again = await enqueue_planned(session, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, planned=visura())
    assert again.id == first.id
    assert await live_count(session, "visure_prepare") == 1


@pytest.mark.asyncio
async def test_asking_again_after_cancelling_creates_a_new_request(session):
    first = await enqueue_planned(session, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, planned=visura("Bianchi Laura"))
    first.status = "cancelled"
    await session.flush()
    second = await enqueue_planned(session, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, planned=visura("Bianchi Laura"))
    assert second.id != first.id
    assert second.status == "queued"
    second.status = "completed"
    await session.flush()
    third = await enqueue_planned(session, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, planned=visura("Bianchi Laura"))
    assert third.id not in {first.id, second.id}
    assert third.status == "queued"
