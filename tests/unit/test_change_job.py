import os
from pathlib import Path

import pytest
from app.database import Base, SessionLocal, engine
from app.models import AgentSlot, Device
from app.routers.ws import rebind_role
from app.seed import DEMO_TENANT_ID, seed_agent_slots


@pytest.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as opened:
        await seed_agent_slots(opened, DEMO_TENANT_ID)
        yield opened


async def a_mac(session, role: str, key: str) -> Device:
    from sqlalchemy import select

    already = (
        await session.execute(
            select(Device).where(Device.tenant_id == DEMO_TENANT_ID, Device.agent_id == role)
        )
    ).scalars().first()
    if already is not None:
        await session.delete(already)
        await session.flush()
    device = Device(
        tenant_id=DEMO_TENANT_ID,
        agent_id=role,
        hostname=f"MacBook-{key}.local",
        display_name=role.upper(),
        public_key=f"chiave-{key}",
        fingerprint=f"fp-{key}",
        capabilities="[]",
        platform="macos",
        status="active",
        presence="online",
    )
    session.add(device)
    await session.flush()
    slot = await slot_for(session, role)
    if slot is not None:
        slot.device_id = device.id
        await session.flush()
    return device


async def slot_for(session, role: str) -> AgentSlot | None:
    from sqlalchemy import select

    return (
        await session.execute(
            select(AgentSlot).where(AgentSlot.tenant_id == DEMO_TENANT_ID, AgentSlot.role == role)
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_changing_job_moves_the_pc_to_the_new_role(session):
    """Cambia lavoro sul Mac: il Director deve dargli davvero quel posto."""

    mac = await a_mac(session, "pc-email", "cambia")
    changed = await rebind_role(session, mac, "pc-visure")
    await session.flush()

    assert changed is True
    assert mac.agent_id == "pc-visure"
    assert mac.display_name == "PC-VISURE"
    assert (await slot_for(session, "pc-visure")).device_id == mac.id
    old = await slot_for(session, "pc-email")
    assert old is None or old.device_id is None


@pytest.mark.asyncio
async def test_the_old_slot_is_released_when_it_exists(session):
    mac = await a_mac(session, "pc-fatture", "libera")
    assert (await slot_for(session, "pc-fatture")).device_id == mac.id
    assert await rebind_role(session, mac, "pc-contabilita") is True
    await session.flush()
    assert (await slot_for(session, "pc-fatture")).device_id is None
    assert (await slot_for(session, "pc-contabilita")).device_id == mac.id


@pytest.mark.asyncio
async def test_it_does_not_steal_a_job_from_another_pc(session):
    mine = await a_mac(session, "pc-email", "mio")
    other = await a_mac(session, "pc-durc", "altro")
    changed = await rebind_role(session, mine, "pc-durc")
    await session.flush()

    assert changed is False
    assert mine.agent_id == "pc-email"
    assert (await slot_for(session, "pc-durc")).device_id == other.id


@pytest.mark.asyncio
async def test_it_does_not_crash_when_another_row_holds_that_role(session):
    """Due righe non possono avere lo stesso ruolo: si rifiuta invece di rompersi."""

    ghost = await a_mac(session, "pc-camerali", "vecchio")
    ghost_slot = await slot_for(session, "pc-camerali")
    ghost_slot.device_id = None
    await session.flush()
    mac = await a_mac(session, "pc-email", "nuovo")

    assert await rebind_role(session, mac, "pc-camerali") is False
    await session.flush()
    assert mac.agent_id == "pc-email"
    assert ghost.agent_id == "pc-camerali"


@pytest.mark.asyncio
async def test_an_invented_role_is_ignored(session):
    mac = await a_mac(session, "pc-visure", "finto")
    assert await rebind_role(session, mac, "pc-inventato") is False
    assert await rebind_role(session, mac, "") is False
    assert await rebind_role(session, mac, "pc-visure") is False
    assert mac.agent_id == "pc-visure"


def test_each_job_gets_its_own_folder_even_with_a_shared_default(tmp_path, monkeypatch):
    """Il lanciatore del Mac imposta una cartella unica: il ruolo deve avere la sua."""

    from agent import mac_boot

    monkeypatch.setattr(mac_boot, "support_dir", lambda: tmp_path)
    monkeypatch.setenv("KRELUNA_AGENT_DATA_DIR", str(tmp_path / "data"))
    mac_boot.apply_config(
        {
            "role": "pc-visure",
            "display_name": "PC-VISURE",
            "director_url": "http://127.0.0.1:8080",
        }
    )
    first = Path(os.environ["KRELUNA_AGENT_DATA_DIR"])
    assert first.name == "pc-visure"

    monkeypatch.setenv("KRELUNA_AGENT_DATA_DIR", str(tmp_path / "data"))
    mac_boot.apply_config(
        {
            "role": "pc-fatture",
            "display_name": "PC-FATTURE",
            "director_url": "http://127.0.0.1:8080",
        }
    )
    second = Path(os.environ["KRELUNA_AGENT_DATA_DIR"])
    assert second.name == "pc-fatture"
    assert first != second, "due lavori non possono condividere la stessa identità"


def test_an_agent_can_forget_only_a_rejected_enrollment(tmp_path):
    from agent.identity import AgentIdentity

    identity = AgentIdentity(tmp_path, "pc-fatture", "PC-FATTURE")
    identity.save_enrollment("vecchio-device", "vecchio-studio")
    key_before = identity.key_path.read_bytes()

    identity.clear_enrollment()

    assert identity.device_id is None
    assert identity.tenant_id is None
    assert not identity.state_path.exists()
    assert identity.key_path.read_bytes() == key_before
