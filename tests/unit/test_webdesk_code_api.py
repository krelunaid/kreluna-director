import json
import time
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from app.config import settings
from app.database import Base, get_session
from app.models import (
    ClientCredential,
    Device,
    GmailConnection,
    Task,
    Tenant,
    User,
    WebdeskMailChallenge,
    WebdeskMailPolicy,
    utcnow,
)
from app.routers.agent_io import router
from app.services.vault import encrypt_credential_fields
from fastapi import FastAPI
from kreluna_shared.crypto import agent_http_payload, b64e, generate_device_keypair, sign_bytes
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def harness(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    private, public = generate_device_keypair()
    async with sessions() as s:
        s.add(Tenant(id="tenant", name="Test", slug="test"))
        s.add(User(id="owner", tenant_id="tenant", role="studio_owner", email="owner@example.test", name="Owner"))
        s.add(Device(id="device", tenant_id="tenant", agent_id="test", hostname="test", public_key=b64e(public), fingerprint="test"))
        s.add(Task(id="task", tenant_id="tenant", requested_by="owner", goal="Test", capability="portal_open",
            status="running", assigned_device_id="device", idempotency_key="test",
            args_json=json.dumps({"portal": "fatture-webdesk", "query": "test", "use_saved_access": True})))
        cred = ClientCredential(id="credential", tenant_id="tenant", client_name="test", client_key="test",
            portal="webdesk", portal_url="https://app.webdesk.it/Apps/Login/View", credential_label="principale", updated_by="owner")
        encrypt_credential_fields(cred, username="TESTUSER", secret="fake-password", portal_account="TEST")
        s.add(cred)
        s.add(GmailConnection(tenant_id="tenant", email="test@example.test", refresh_ciphertext="fake-ciphertext", updated_by="owner"))
        s.add(WebdeskMailPolicy(tenant_id="tenant", enabled=True, updated_by="owner"))
        await s.commit()
    app = FastAPI()
    app.include_router(router)
    async def session_dependency():
        async with sessions() as s: yield s
    app.dependency_overrides[get_session] = session_dependency
    monkeypatch.setattr(settings, "director_public_url", "https://director.example.test")
    def sign(path, **overrides):
        body = {"device_id": "device", "task_id": "task", "recipient": "test@example.test",
                "challenge_id": "", "nonce": uuid4().hex, "sent_at": int(time.time()), **overrides}
        return {**body, "signature": b64e(sign_bytes(private, agent_http_payload(path, body)))}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions, sign
    await engine.dispose()


async def test_single_use_signed_delivery(harness, monkeypatch):
    client, sessions, sign = harness
    start, poll = "/agent/webdesk-code/start", "/agent/webdesk-code/poll"
    body = sign(start)
    tampered = {**body, "recipient": "other@example.test"}
    assert (await client.post(start, json=tampered)).status_code == 401
    started = await client.post(start, json=body)
    assert started.status_code == 200, started.text
    challenge = started.json()["challenge_id"]
    assert (await client.post(start, json=sign(start))).status_code == 409
    async def read(*args):
        assert args[-1] == "TESTUSER"
        return "message-id", "123456"
    monkeypatch.setattr("app.routers.agent_io.read_validation_code", read)
    received = await client.post(poll, json=sign(poll, challenge_id=challenge))
    assert received.status_code == 200, received.text
    assert received.json() == {"pending": False, "code": "123456"}
    assert received.headers["cache-control"] == "no-store"
    assert (await client.post(poll, json=sign(poll, challenge_id=challenge))).status_code == 409
    async with sessions() as s:
        row = await s.get(WebdeskMailChallenge, "tenant")
        assert row.consumed
        assert "123456" not in str(row.__dict__)


async def test_access_only_webdesk_uses_unique_studio_credential(harness):
    client, sessions, sign = harness
    async with sessions() as s:
        task = await s.get(Task, "task")
        args = json.loads(task.args_json)
        args["query"] = ""
        task.args_json = json.dumps(args)
        await s.commit()
    path = "/agent/webdesk-code/start"
    assert (await client.post(path, json=sign(path))).status_code == 200


@pytest.mark.parametrize("consumed", [False, True])
async def test_new_job_can_replace_only_consumed_challenge(harness, consumed):
    client, sessions, sign = harness
    start = "/agent/webdesk-code/start"
    original = (await client.post(start, json=sign(start))).json()["challenge_id"]
    async with sessions() as s:
        old = await s.get(Task, "task")
        s.add(Task(id="next", tenant_id="tenant", requested_by="owner", goal="Test next",
                   capability="portal_open", status="running", assigned_device_id="device",
                   idempotency_key="next", args_json=old.args_json))
        (await s.get(WebdeskMailChallenge, "tenant")).consumed = consumed
        await s.commit()
    # Even after consumption the same task must never request another code.
    assert (await client.post(start, json=sign(start))).status_code == 409
    response = await client.post(start, json=sign(start, task_id="next"))
    assert response.status_code == (200 if consumed else 409)
    async with sessions() as s:
        current = await s.get(WebdeskMailChallenge, "tenant")
        assert (current.id != original) == consumed
        assert current.task_id == ("next" if consumed else "task")


@pytest.mark.parametrize("change", ["disabled", "cancelled", "device", "expired", "connection", "other_portal"])
async def test_authority_rechecked_before_reading(harness, monkeypatch, change):
    client, sessions, sign = harness
    start, poll = "/agent/webdesk-code/start", "/agent/webdesk-code/poll"
    challenge = (await client.post(start, json=sign(start))).json()["challenge_id"]
    async with sessions() as s:
        if change == "disabled": (await s.get(WebdeskMailPolicy, "tenant")).enabled = False
        if change == "cancelled": (await s.get(Task, "task")).status = "cancelled"
        if change == "device": (await s.get(Device, "device")).paused = True
        if change == "expired": (await s.get(WebdeskMailChallenge, "tenant")).expires_at = utcnow()-timedelta(seconds=1)
        if change == "connection": (await s.get(GmailConnection, "tenant")).refresh_ciphertext = "replaced"
        if change == "other_portal": (await s.get(Task, "task")).args_json = '{"portal":"contratti-ade","query":"test","use_saved_access":true}'
        await s.commit()
    async def forbidden(*args): raise AssertionError("Must not read Gmail")
    monkeypatch.setattr("app.routers.agent_io.read_validation_code", forbidden)
    assert (await client.post(poll, json=sign(poll, challenge_id=challenge))).status_code in {401,403,404,409}
