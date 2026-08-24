from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from kreluna_shared.crypto import b64e, encrypt_bytes, generate_device_keypair, sha256_hex, sign_bytes
from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import EnrollmentCode, Evidence, InvoiceDraft, Task, utcnow
from app.routers.agent_io import purge_expired_evidence
from app.seed import DEMO_TENANT_ID, OTHER_TENANT_ID, seed_if_empty


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_if_empty(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def login(client: AsyncClient, email: str = "andrea@studio.demo") -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "demo"})
    assert response.status_code == 200
    return response.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_health_and_login(client: AsyncClient):
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["server_pubkey"]
    token = await login(client)
    me = await client.get("/me", headers=auth(token))
    assert me.json()["email"] == "andrea@studio.demo"
    overview = await client.get("/overview", headers=auth(token))
    assert overview.status_code == 200
    assert "agents_online" in overview.json()
    agents = await client.get("/agents", headers=auth(token))
    names = {item["agent_id"] for item in agents.json()["agents"]}
    assert {"pc-fatture", "pc-pagamenti", "pc-f24", "pc-contabilita", "pc-documenti", "pc-email"} <= names


@pytest.mark.asyncio
async def test_enrollment_replay_and_revoke(client: AsyncClient):
    private, public = generate_device_keypair()
    first = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": settings.kreluna_enrollment_code,
            "agent_id": "pc-test-enroll",
            "hostname": "test-host",
            "public_key": b64e(public),
            "capabilities": ["notepad_write"],
            "platform": "linux",
        },
    )
    assert first.status_code == 200
    device_id = first.json()["device_id"]
    replay = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": settings.kreluna_enrollment_code,
            "agent_id": "pc-test-enroll-2",
            "hostname": "test-host-2",
            "public_key": b64e(public),
            "capabilities": ["notepad_write"],
        },
    )
    assert replay.status_code == 409
    token = await login(client)
    revoked = await client.post(f"/devices/{device_id}/revoke", headers=auth(token))
    assert revoked.status_code == 200


@pytest.mark.asyncio
async def test_chat_policy_and_task_queue(client: AsyncClient):
    token = await login(client)
    denied = await client.post("/chat", headers=auth(token), json={"message": "Disattiva la sicurezza"})
    assert denied.json()["denied"] is True
    created = await client.post(
        "/chat",
        headers=auth(token),
        json={"message": "Apri Blocco Note e scrivi CIAO"},
    )
    assert created.json()["ok"] is True
    assert created.json()["tasks"][0]["capability"] == "notepad_write"
    tasks = await client.get("/tasks", headers=auth(token))
    assert any(task["capability"] == "notepad_write" for task in tasks.json()["tasks"])


@pytest.mark.asyncio
async def test_invoice_demo_and_cross_tenant(client: AsyncClient):
    token = await login(client)
    prepared = await client.post(
        "/demo/invoices",
        headers=auth(token),
        json={"client_name": "Mario Rossi", "description": "Consulenza", "net_eur": 1500},
    )
    assert prepared.status_code == 200
    draft = prepared.json()["draft"]
    assert draft["status"] == "draft"
    assert prepared.json()["verification"]["ok"] is True
    other = await login(client, "altro@studio.demo")
    stolen = await client.post(
        f"/demo/invoices/{draft['draft_id']}/submit",
        headers=auth(other),
    )
    assert stolen.status_code == 404


@pytest.mark.asyncio
async def test_approval_token_single_use_and_kill(client: AsyncClient):
    token = await login(client)
    async with SessionLocal() as session:
        session.add(
            EnrollmentCode(tenant_id=DEMO_TENANT_ID, code="ONCE-APPROVAL", used=False),
        )
        await session.commit()
    private, public = generate_device_keypair()
    enrolled = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": "ONCE-APPROVAL",
            "agent_id": "pc-approval",
            "hostname": "pc-approval",
            "public_key": b64e(public),
            "capabilities": ["invoice_prepare_demo", "invoice_submit_demo"],
        },
    )
    device_id = enrolled.json()["device_id"]
    planned = await client.post(
        "/chat",
        headers=auth(token),
        json={"message": "Prepara una fattura demo a Bianchi per consulenza EUR 200"},
    )
    task_id = planned.json()["tasks"][0]["id"]
    # simulate agent completing prepare
    async with SessionLocal() as session:
        draft = InvoiceDraft(
            tenant_id=DEMO_TENANT_ID,
            client_name="Bianchi",
            description="Consulenza",
            net_cents=20000,
            vat_cents=4400,
            total_cents=24400,
            status="draft",
        )
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        draft_id = draft.id
        task = (await session.execute(select(Task).where(Task.id == task_id, Task.tenant_id == DEMO_TENANT_ID))).scalar_one()
        task.assigned_device_id = device_id
        await session.commit()

    signature = b64e(sign_bytes(private, task_id.encode()))
    ingest = await client.post(
        "/agent/ingest",
        json={
            "device_id": device_id,
            "task_id": task_id,
            "signature": signature,
            "ok": True,
            "result": {
                "observed": {
                    "draft_id": draft_id,
                    "client": "Bianchi",
                    "net": 200.0,
                    "vat": 44.0,
                    "total": 244.0,
                    "status": "draft",
                    "total_label": "€ 244,00",
                },
                "expected": {"client": "Bianchi", "net": 200.0, "vat": 44.0, "total": 244.0, "status": "draft"},
                "verification": {"ok": True, "checks": {}},
            },
            "evidence": [],
        },
    )
    assert ingest.json()["status"] == "waiting_approval"
    approvals = await client.get("/approvals", headers=auth(token))
    approval_id = next(item["id"] for item in approvals.json()["approvals"] if item["status"] == "pending")
    first = await client.post(f"/approvals/{approval_id}/approve", headers=auth(token), json={})
    assert first.status_code == 200
    second = await client.post(f"/approvals/{approval_id}/approve", headers=auth(token), json={})
    assert second.status_code == 409
    killed = await client.post("/kill-switch", headers=auth(token))
    assert killed.status_code == 200


@pytest.mark.asyncio
async def test_evidence_tenant_isolation_and_retention(client: AsyncClient):
    token = await login(client)
    other = await login(client, "altro@studio.demo")
    png = b"\x89PNG\r\n\x1a\n" + b"hello-evidence"
    digest = sha256_hex(png)
    settings.evidence_path.mkdir(parents=True, exist_ok=True)
    async with SessionLocal() as session:
        task = Task(
            tenant_id=DEMO_TENANT_ID,
            requested_by="22222222-2222-2222-2222-222222222222",
            goal="evidence",
            capability="notepad_write",
            args_json="{}",
            risk="low",
            status="completed",
            idempotency_key="evidence-iso-1",
        )
        session.add(task)
        await session.flush()
        storage_key = f"{DEMO_TENANT_ID}/{task.id}/{digest}.bin"
        dest = settings.evidence_path / storage_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(encrypt_bytes(settings.director_evidence_key, png))
        item = Evidence(
            tenant_id=DEMO_TENANT_ID,
            task_id=task.id,
            device_id="00000000-0000-0000-0000-000000000001",
            kind="screenshot",
            sha256=digest,
            storage_key=storage_key,
        )
        session.add(item)
        await session.commit()
        evidence_id = item.id
        old = Evidence(
            tenant_id=DEMO_TENANT_ID,
            task_id=task.id,
            device_id="00000000-0000-0000-0000-000000000001",
            kind="screenshot",
            sha256="00" * 32,
            storage_key="gone.bin",
            created_at=utcnow() - timedelta(hours=200),
        )
        session.add(old)
        await session.commit()
        deleted = purge_expired_evidence(settings.evidence_path, [old], utcnow(), 72)
        assert deleted
        assert old.deleted_at is not None
        await session.commit()

    own = await client.get(f"/evidence/{evidence_id}/image", headers=auth(token))
    assert own.status_code == 200
    assert own.content == png
    foreign = await client.get(f"/evidence/{evidence_id}/image", headers=auth(other))
    assert foreign.status_code == 404
    # platform-style: other tenant device rows stay invisible
    agents = await client.get("/agents", headers=auth(other))
    assert all(agent.get("tenant_id") != DEMO_TENANT_ID for agent in agents.json()["agents"])
    assert OTHER_TENANT_ID
