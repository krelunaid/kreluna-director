from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    AgentSlot,
    AIProviderCredential,
    AuditEvent,
    ClientCredential,
    EnrollmentCode,
    Evidence,
    InvoiceDraft,
    Task,
    VaultPin,
    WorkspaceDocument,
    utcnow,
)
from app.routers.agent_io import purge_expired_evidence
from app.security import read_session
from app.seed import DEMO_TENANT_ID, OTHER_TENANT_ID, seed_if_empty
from app.services.vault import decrypt_credential
from httpx import ASGITransport, AsyncClient
from kreluna_shared.crypto import (
    agent_http_payload,
    b64e,
    canonical_json_bytes,
    encrypt_bytes,
    generate_device_keypair,
    sha256_hex,
    sign_bytes,
)
from kreluna_shared.planner import plan_deterministic
from sqlalchemy import select


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


@pytest.mark.asyncio
async def test_login_remembers_device_without_returning_password(client: AsyncClient):
    started = int(time.time())
    response = await client.post(
        "/auth/login",
        json={
            "email": "andrea@studio.demo",
            "password": "demo",
            "remember_device": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "password" not in body
    claims = read_session(settings.director_session_secret, body["token"])
    assert claims["persistent"] is True
    assert claims["exp"] - started >= settings.director_remember_session_ttl_seconds - 2

    refreshed = await client.post(
        "/auth/refresh",
        headers=auth(body["token"]),
        json={"remember_device": True},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["expires_in"] == settings.director_remember_session_ttl_seconds


@pytest.mark.asyncio
async def test_owner_can_configure_remote_link_without_token_disclosure(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "director_remote_dir", str(tmp_path))
    monkeypatch.setattr(settings, "director_cloudflared_path", str(tmp_path / "missing-cloudflared"))
    monkeypatch.setattr(settings, "director_public_url", settings.director_public_url)
    owner = await login(client)
    secret = "R" * 100

    configured = await client.post(
        "/remote/configure",
        headers=auth(owner),
        json={
            "public_url": "https://director.studio.example",
            "tunnel_token": secret,
        },
    )

    assert configured.status_code == 200
    assert configured.json()["configured"] is True
    assert configured.json()["connector_available"] is False
    assert secret not in configured.text
    assert (tmp_path / "remote-tunnel.token").read_text().strip() == secret


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def unlock_fort_knox(
    client: AsyncClient,
    token: str,
    pin: str = "654321",
) -> dict[str, str]:
    headers = auth(token)
    status = await client.get("/vault/pin/status", headers=headers)
    assert status.status_code == 200
    if not status.json()["configured"]:
        configured = await client.post(
            "/vault/pin/configure", headers=headers, json={"pin": pin}
        )
        assert configured.status_code == 201
    unlocked = await client.post("/vault/unlock", headers=headers, json={"pin": pin})
    assert unlocked.status_code == 200
    return {**headers, "X-Vault-Grant": unlocked.json()["grant"]}


async def issue_agent_code(
    client: AsyncClient,
    role: str,
    capabilities: list[str],
) -> str:
    async with SessionLocal() as session:
        slot = (
            await session.execute(
                select(AgentSlot).where(
                    AgentSlot.tenant_id == DEMO_TENANT_ID,
                    AgentSlot.role == role,
                )
            )
        ).scalar_one_or_none()
        if slot is None:
            session.add(
                AgentSlot(
                    tenant_id=DEMO_TENANT_ID,
                    role=role,
                    display_name=role.upper(),
                    job="Test",
                    program="Test locale",
                    capabilities=json.dumps(capabilities),
                    enrollment_code="",
                )
            )
            await session.commit()
    owner = await login(client)
    issued = await client.post(f"/agents/{role}/enrollment", headers=auth(owner))
    assert issued.status_code == 200, issued.text
    return issued.json()["enrollment_code"]


async def enroll_test_agent(
    client: AsyncClient,
    *,
    role: str,
    capabilities: list[str],
    platform: str = "macos",
) -> tuple[bytes, str, str]:
    code = await issue_agent_code(client, role, capabilities)
    private, public = generate_device_keypair()
    enrolled = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": code,
            "agent_id": role,
            "hostname": f"{role}-host",
            "public_key": b64e(public),
            "capabilities": capabilities,
            "platform": platform,
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    return private, enrolled.json()["device_id"], code


def signed_ingest(
    private_key: bytes,
    *,
    device_id: str,
    task_id: str,
    ok: bool,
    result: dict | None = None,
    error: str | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    envelope = {
        "device_id": device_id,
        "task_id": task_id,
        "nonce": uuid4().hex,
        "sent_at": int(time.time()),
        "ok": ok,
        "result": result or {},
        "error": error,
        "evidence": evidence or [],
    }
    return {
        **envelope,
        "signature": b64e(sign_bytes(private_key, canonical_json_bytes(envelope))),
    }


def signed_agent_request(private_key: bytes, path: str, payload: dict) -> dict:
    envelope = {
        **payload,
        "nonce": uuid4().hex,
        "sent_at": int(time.time()),
    }
    return {
        **envelope,
        "signature": b64e(sign_bytes(private_key, agent_http_payload(path, envelope))),
    }


@pytest.fixture
def planned_by_test_model(monkeypatch):
    """Le integrazioni collaudano la coda con un modello locale prevedibile."""

    async def plan(message: str, **_kwargs):
        result = plan_deterministic(message)
        if not result.denied and result.source != "deterministic-kill":
            result.source = "llm"
        return result

    monkeypatch.setattr("app.routers.work.plan_message", plan)


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
    assert {
        "pc-fatture",
        "pc-f24",
        "pc-contabilita",
        "pc-camerali",
        "pc-contratti",
        "pc-durc",
        "pc-visure",
    } <= names
    assert "pc-pagamenti" not in names
    assert "pc-email" not in names
    programs = {item["agent_id"]: item.get("program") or "" for item in agents.json()["agents"]}
    assert "Webdesk" in programs["pc-fatture"]
    assert "IPSOA" in programs["pc-f24"]
    assert "CGN" in programs["pc-visure"]
    assert overview.json()["agents_total"] == len(agents.json()["agents"])


@pytest.mark.asyncio
async def test_fort_knox_requires_pin_and_scoped_temporary_grant(client: AsyncClient):
    token = await login(client)
    assert (await client.get("/vault/credentials", headers=auth(token))).status_code == 423

    configured = await client.post(
        "/vault/pin/configure", headers=auth(token), json={"pin": "654321"}
    )
    assert configured.status_code == 201
    assert "654321" not in configured.text
    async with SessionLocal() as session:
        stored = await session.get(VaultPin, DEMO_TENANT_ID)
        assert stored is not None
        assert stored.pin_hash.startswith("$argon2id$")
        assert "654321" not in stored.pin_hash

    wrong = await client.post(
        "/vault/unlock", headers=auth(token), json={"pin": "000000"}
    )
    assert wrong.status_code == 403
    assert "000000" not in wrong.text
    unlocked = await client.post(
        "/vault/unlock", headers=auth(token), json={"pin": "654321"}
    )
    assert unlocked.status_code == 200
    grant = unlocked.json()["grant"]
    assert "654321" not in grant
    assert (
        await client.get(
            "/vault/credentials",
            headers={**auth(token), "X-Vault-Grant": grant},
        )
    ).status_code == 200
    assert (
        await client.get(
            "/vault/credentials",
            headers={**auth(token), "X-Vault-Grant": "non-valido"},
        )
    ).status_code == 423


@pytest.mark.asyncio
async def test_owner_manages_fort_knox_without_exposing_plaintext(client: AsyncClient):
    token = await login(client)
    vault = await unlock_fort_knox(client, token)
    client_name = f"Cliente Fort Knox {uuid4()}"
    secret = "Fort-Knox-Segreto-123"
    created = await client.post(
        "/vault/credentials",
        headers=vault,
        json={
            "client_name": client_name,
            "portal": "webdesk",
            "portal_url": "https://fatture.example.it/login",
            "username": "fortknox@example.it",
            "secret": secret,
            "secret_kind": "password",
            "credential_label": "principale",
        },
    )
    assert created.status_code == 201
    assert created.json()["sent_to_ai"] is False
    assert secret not in created.text
    credential_id = created.json()["id"]

    duplicate = await client.post(
        "/vault/credentials",
        headers=vault,
        json={
            "client_name": client_name,
            "portal": "webdesk",
            "portal_url": "https://fatture.example.it/login",
            "username": "altro@example.it",
            "secret": "Altro-Segreto-123",
            "secret_kind": "password",
            "credential_label": "principale",
        },
    )
    assert duplicate.status_code == 409

    replacement = "Fort-Knox-Nuovo-Segreto-456"
    updated = await client.put(
        f"/vault/credentials/{credential_id}",
        headers=vault,
        json={
            "client_name": client_name,
            "portal": "webdesk",
            "portal_url": "https://fatture.example.it/accesso",
            "username": "fortknox-nuovo@example.it",
            "secret": replacement,
            "secret_kind": "password",
            "credential_label": "principale",
        },
    )
    assert updated.status_code == 200
    assert replacement not in updated.text

    listing = await client.get("/vault/credentials", headers=vault)
    item = next(row for row in listing.json()["credentials"] if row["id"] == credential_id)
    assert item["portal_url"] == "https://fatture.example.it/accesso"
    assert item["username_masked"] != "fortknox-nuovo@example.it"
    assert replacement not in listing.text
    async with SessionLocal() as session:
        stored = (
            await session.execute(
                select(ClientCredential).where(ClientCredential.id == credential_id)
            )
        ).scalar_one()
        assert replacement not in stored.secret_ciphertext
        assert decrypt_credential(stored) == ("fortknox-nuovo@example.it", replacement)

    other_owner = await login(client, "altro@studio.demo")
    other_vault = await unlock_fort_knox(client, other_owner)
    other_listing = await client.get("/vault/credentials", headers=other_vault)
    assert credential_id not in other_listing.text

    viewer = await login(client, "viewer@studio.demo")
    denied = await client.post(
        "/vault/credentials",
        headers=auth(viewer),
        json={
            "client_name": "Cliente vietato",
            "portal": "webdesk",
            "username": "viewer",
            "secret": "Segreto-Viewer-123",
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_fort_knox_api_refuses_spid_cns_cie_and_otp(client: AsyncClient):
    token = await login(client)
    vault = await unlock_fort_knox(client, token)
    for portal in ("spid", "cns", "cie", "smart-card", "otp"):
        denied = await client.post(
            "/vault/credentials",
            headers=vault,
            json={
                "client_name": f"Cliente {portal}",
                "portal": portal,
                "username": "utente",
                "secret": "Segreto-Non-Salvabile",
            },
        )
        assert denied.status_code == 400
        assert "manuali" in denied.text


@pytest.mark.asyncio
async def test_owner_imports_masked_client_credentials_without_plaintext(client: AsyncClient):
    token = await login(client)
    vault = await unlock_fort_knox(client, token)
    csv_data = (
        b"cliente;portale;username;password;tipo_segreto;etichetta\n"
        b"Cliente Cassaforte;webdesk;cassaforte@example.it;Segreto-Non-In-DB;password;principale\n"
    )
    preview = await client.post(
        "/vault/import/preview",
        headers=vault,
        files={"file": ("accessi.csv", csv_data, "text/csv")},
    )
    assert preview.status_code == 200
    assert preview.json()["recognized"] == 1
    assert preview.json()["sent_to_ai"] is False
    assert "Segreto-Non-In-DB" not in preview.text

    imported = await client.post(
        "/vault/import",
        headers=vault,
        files={"file": ("accessi.csv", csv_data, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 1
    assert imported.json()["source_file_retained"] is False
    listing = await client.get("/vault/credentials", headers=vault)
    assert listing.status_code == 200
    item = next(row for row in listing.json()["credentials"] if row["client_name"] == "Cliente Cassaforte")
    assert item["username_masked"] != "cassaforte@example.it"
    assert "Segreto-Non-In-DB" not in listing.text

    async with SessionLocal() as session:
        stored = (
            await session.execute(
                select(ClientCredential).where(ClientCredential.id == item["id"])
            )
        ).scalar_one()
        assert "cassaforte@example.it" not in stored.username_ciphertext
        assert "Segreto-Non-In-DB" not in stored.secret_ciphertext

    viewer = await login(client, "viewer@studio.demo")
    assert (await client.get("/vault/credentials", headers=auth(viewer))).status_code == 403
    checked = await client.post(f"/vault/credentials/{item['id']}/check", headers=vault)
    assert checked.json()["state"] == "ready"
    revoked = await client.delete(f"/vault/credentials/{item['id']}", headers=vault)
    assert revoked.status_code == 200
    listing = await client.get("/vault/credentials", headers=vault)
    assert all(row["id"] != item["id"] for row in listing.json()["credentials"])


@pytest.mark.asyncio
async def test_fort_knox_locks_after_five_wrong_pins(client: AsyncClient):
    token = await login(client, "altro@studio.demo")
    await unlock_fort_knox(client, token)
    for attempt in range(5):
        denied = await client.post(
            "/vault/unlock", headers=auth(token), json={"pin": "111111"}
        )
        assert denied.status_code == (429 if attempt == 4 else 403)
    status = await client.get("/vault/pin/status", headers=auth(token))
    assert status.json()["locked"] is True
    assert status.json()["retry_after"] > 0
    assert status.json()["security_alert"] is True
    assert status.json()["blocked_attempts"] == 1
    still_locked = await client.post(
        "/vault/unlock", headers=auth(token), json={"pin": "654321"}
    )
    assert still_locked.status_code == 429
    for _ in range(8):
        blocked = await client.post(
            "/vault/unlock", headers=auth(token), json={"pin": "111111"}
        )
        assert blocked.status_code == 429

    status = await client.get("/vault/pin/status", headers=auth(token))
    assert status.json()["security_alert"] is True
    assert status.json()["blocked_attempts"] == 10

    overview = await client.get("/overview", headers=auth(token))
    assert overview.json()["vault_security_alerts"] == 1
    assert overview.json()["vault_blocked_attempts"] == 10
    assert overview.json()["vault_locked"] is True

    async with SessionLocal() as session:
        checkpoints = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == OTHER_TENANT_ID,
                    AuditEvent.action == "fort_knox.lockout_aggregate",
                )
            )
        ).scalars().all()
        assert checkpoints[-1].detail.split(";", 1)[0] == "blocked_attempts=10"
        pin = await session.get(VaultPin, OTHER_TENANT_ID)
        assert pin is not None
        pin.locked_until = utcnow() - timedelta(seconds=1)
        await session.commit()

    reopened = await client.post(
        "/vault/unlock", headers=auth(token), json={"pin": "654321"}
    )
    assert reopened.status_code == 200
    cleared = await client.get("/vault/pin/status", headers=auth(token))
    assert cleared.json()["blocked_attempts"] == 0
    assert cleared.json()["security_alert"] is False


@pytest.mark.asyncio
async def test_document_library_crud_download_encryption_and_tenant_isolation(client: AsyncClient):
    token = await login(client)
    headers = auth(token)
    title = f"Contratto prova {uuid4()}"
    original = "Bozza privata dello studio\nClausola iniziale"
    created = await client.post(
        "/library/text",
        headers=headers,
        json={"category": "contract", "title": title, "content": original, "notes": "Bozza"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["editable"] is True

    listing = await client.get("/library?category=contract", headers=headers)
    assert listing.status_code == 200
    assert any(item["id"] == document_id for item in listing.json()["documents"])

    text = await client.get(f"/library/{document_id}/text", headers=headers)
    assert text.status_code == 200
    assert text.json()["content"] == original

    downloaded = await client.get(
        f"/library/{document_id}/file?disposition=attachment", headers=headers
    )
    assert downloaded.status_code == 200
    assert downloaded.content.decode() == original
    assert "attachment" in downloaded.headers["content-disposition"]

    updated = await client.put(
        f"/library/{document_id}",
        headers=headers,
        json={"title": "Contratto aggiornato", "notes": "Controllato", "content": "Nuovo testo"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Contratto aggiornato"
    assert (await client.get(f"/library/{document_id}/text", headers=headers)).json()["content"] == "Nuovo testo"

    async with SessionLocal() as session:
        row = await session.get(WorkspaceDocument, document_id)
        assert row is not None
        encrypted = (settings.evidence_path.parent / "documents" / row.storage_key).read_bytes()
        assert b"Nuovo testo" not in encrypted

    other = await login(client, "altro@studio.demo")
    assert (await client.get(f"/library/{document_id}/text", headers=auth(other))).status_code == 404
    viewer = await login(client, "viewer@studio.demo")
    assert (await client.delete(f"/library/{document_id}", headers=auth(viewer))).status_code == 403

    deleted = await client.delete(f"/library/{document_id}", headers=headers)
    assert deleted.status_code == 200
    assert (await client.get(f"/library/{document_id}/text", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_document_library_uploads_pdf_and_refuses_binary_content_edit(client: AsyncClient):
    token = await login(client)
    headers = auth(token)
    uploaded = await client.post(
        "/library/upload",
        headers=headers,
        data={"category": "document", "title": "Documento PDF", "notes": "Allegato"},
        files={"file": ("documento.pdf", b"%PDF-1.4\nprova", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["previewable"] is True
    assert body["editable"] is False

    metadata = await client.put(
        f"/library/{body['id']}",
        headers=headers,
        json={"title": "PDF rinominato", "notes": "Nuova nota"},
    )
    assert metadata.status_code == 200
    refused = await client.put(
        f"/library/{body['id']}",
        headers=headers,
        json={"title": "PDF", "notes": "", "content": "non consentito"},
    )
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_assigned_agent_receives_one_single_use_vault_lease(client: AsyncClient):
    token = await login(client)
    vault = await unlock_fort_knox(client, token)
    csv_data = (
        b"cliente;portale;link_portale;username;password\n"
        b"Cliente Lease;webdesk;https://fatture.example.it/login;"
        b"lease@example.it;Lease-Segreto-123\n"
    )
    imported = await client.post(
        "/vault/import",
        headers=vault,
        files={"file": ("accessi.csv", csv_data, "text/csv")},
    )
    assert imported.status_code == 200
    private, device_id, _code = await enroll_test_agent(
        client,
        role=f"pc-lease-{uuid4()}",
        capabilities=["portal_open"],
    )
    async with SessionLocal() as session:
        task = Task(
            tenant_id=DEMO_TENANT_ID,
            requested_by="22222222-2222-2222-2222-222222222222",
            goal="Compilare accesso salvato",
            capability="portal_open",
            args_json=(
                '{"portal":"fatture-webdesk","query":"Cliente Lease",'
                '"use_saved_access":true}'
            ),
            risk="medium",
            status="assigned",
            idempotency_key=f"lease-{uuid4()}",
            assigned_device_id=device_id,
        )
        session.add(task)
        await session.commit()
        task_id = task.id
    path = "/agent/credential-lease"
    payload = signed_agent_request(
        private,
        path,
        {"device_id": device_id, "task_id": task_id},
    )
    tampered = {**payload, "task_id": str(uuid4())}
    assert (await client.post(path, json=tampered)).status_code == 401
    assert (await client.post("/agent/demo-invoice/prepare", json=payload)).status_code == 401
    location_path = "/agent/portal-location"
    location_payload = signed_agent_request(
        private,
        location_path,
        {"device_id": device_id, "task_id": task_id},
    )
    location = await client.post(location_path, json=location_payload)
    assert location.status_code == 200
    assert location.json()["portal_url"] == "https://fatture.example.it/login"
    assert location.json()["sent_to_ai"] is False
    lease = await client.post("/agent/credential-lease", json=payload)
    assert lease.status_code == 200
    assert lease.json()["username"] == "lease@example.it"
    assert lease.json()["secret"] == "Lease-Segreto-123"
    assert lease.json()["single_use"] is True
    assert (await client.post("/agent/credential-lease", json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_enrollment_replay_and_revoke(client: AsyncClient):
    role = f"pc-test-enroll-{uuid4()}"
    _private, device_id, code = await enroll_test_agent(
        client,
        role=role,
        capabilities=["notepad_write"],
        platform="linux",
    )
    _other_private, other_public = generate_device_keypair()
    replay = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": code,
            "agent_id": role,
            "hostname": "test-host-2",
            "public_key": b64e(other_public),
            "capabilities": ["notepad_write"],
        },
    )
    assert replay.status_code == 409
    async with SessionLocal() as session:
        stored = (
            await session.execute(
                select(EnrollmentCode).where(EnrollmentCode.used_by_device_id == device_id)
            )
        ).scalar_one()
        assert stored.code != code
        assert stored.code.startswith("sha256:")
    token = await login(client)
    revoked = await client.post(f"/devices/{device_id}/revoke", headers=auth(token))
    assert revoked.status_code == 200


@pytest.mark.asyncio
async def test_predictable_and_expired_enrollment_codes_are_rejected(client: AsyncClient):
    _, public = generate_device_keypair()
    predictable = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": "KRELUNA-PC-FATTURE",
            "agent_id": "pc-fatture",
            "hostname": "intruso",
            "public_key": b64e(public),
            "capabilities": ["invoice_prepare_demo"],
        },
    )
    assert predictable.status_code == 401

    role = f"pc-expired-{uuid4()}"
    code = await issue_agent_code(client, role, ["notepad_write"])
    async with SessionLocal() as session:
        record = (
            await session.execute(
                select(EnrollmentCode).where(EnrollmentCode.agent_id == role)
            )
        ).scalar_one()
        record.expires_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    expired = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": code,
            "agent_id": role,
            "hostname": "troppo-tardi",
            "public_key": b64e(public),
            "capabilities": ["notepad_write"],
        },
    )
    assert expired.status_code == 410


@pytest.mark.asyncio
async def test_agent_result_signature_covers_payload_assignment_and_nonce(client: AsyncClient):
    role = f"pc-signed-result-{uuid4()}"
    private, device_id, _code = await enroll_test_agent(
        client,
        role=role,
        capabilities=["notepad_write"],
    )
    other_private, other_device_id, _other_code = await enroll_test_agent(
        client,
        role=f"pc-other-result-{uuid4()}",
        capabilities=["notepad_write"],
    )
    async with SessionLocal() as session:
        task = Task(
            tenant_id=DEMO_TENANT_ID,
            requested_by="22222222-2222-2222-2222-222222222222",
            goal="Risultato firmato",
            capability="notepad_write",
            args_json="{}",
            risk="low",
            status="assigned",
            idempotency_key=f"signed-result-{uuid4()}",
            assigned_device_id=device_id,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    payload = signed_ingest(
        private,
        device_id=device_id,
        task_id=task_id,
        ok=True,
        result={"text": "originale"},
    )
    tampered = {**payload, "result": {"text": "alterato"}}
    assert (await client.post("/agent/ingest", json=tampered)).status_code == 401

    wrong_device = signed_ingest(
        other_private,
        device_id=other_device_id,
        task_id=task_id,
        ok=True,
        result={"text": "rubato"},
    )
    assert (await client.post("/agent/ingest", json=wrong_device)).status_code == 403

    accepted = await client.post("/agent/ingest", json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "completed"
    assert (await client.post("/agent/ingest", json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_owner_can_pause_and_resume_one_agent(client: AsyncClient):
    suffix = str(uuid4())
    _private, device_id, _code = await enroll_test_agent(
        client,
        role=f"pc-pause-{suffix}",
        capabilities=["notepad_write"],
    )
    token = await login(client)

    paused = await client.post(f"/agents/{device_id}/pause", headers=auth(token))
    assert paused.status_code == 200
    agents = (await client.get("/agents", headers=auth(token))).json()["agents"]
    agent = next(item for item in agents if item["device_id"] == device_id)
    assert agent["paused"] is True
    assert agent["presence"] == "paused"

    other = await login(client, "altro@studio.demo")
    assert (await client.post(f"/agents/{device_id}/resume", headers=auth(other))).status_code == 404
    resumed = await client.post(f"/agents/{device_id}/resume", headers=auth(token))
    assert resumed.status_code == 200
    agents = (await client.get("/agents", headers=auth(token))).json()["agents"]
    agent = next(item for item in agents if item["device_id"] == device_id)
    assert agent["paused"] is False


@pytest.mark.asyncio
async def test_reinstall_requires_owner_revoke_and_a_fresh_code(client: AsyncClient):
    role = f"pc-reinstall-{uuid4()}"
    _private, device_id, first_code = await enroll_test_agent(
        client,
        role=role,
        capabilities=["invoice_prepare_demo"],
        platform="windows",
    )
    _, public2 = generate_device_keypair()
    again = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": first_code,
            "agent_id": role,
            "hostname": "pc-fatture-1",
            "public_key": b64e(public2),
            "capabilities": ["invoice_prepare_demo"],
            "platform": "windows",
        },
    )
    assert again.status_code == 409
    owner = await login(client)
    blocked_code = await client.post(f"/agents/{role}/enrollment", headers=auth(owner))
    assert blocked_code.status_code == 409
    assert (await client.post(f"/devices/{device_id}/revoke", headers=auth(owner))).status_code == 200
    replacement_code = await issue_agent_code(client, role, ["invoice_prepare_demo"])
    wrong = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": replacement_code,
            "agent_id": "pc-pagamenti",
            "hostname": "altro",
            "public_key": b64e(public2),
            "capabilities": ["payment_prepare"],
            "platform": "windows",
        },
    )
    assert wrong.status_code == 400
    replacement = await client.post(
        "/enrollment/redeem",
        json={
            "enrollment_code": replacement_code,
            "agent_id": role,
            "hostname": "pc-fatture-1",
            "public_key": b64e(public2),
            "capabilities": ["invoice_prepare_demo"],
            "platform": "windows",
        },
    )
    assert replacement.status_code == 200
    assert replacement.json()["device_id"] == device_id


@pytest.mark.asyncio
async def test_chat_policy_and_task_queue(client: AsyncClient, planned_by_test_model):
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
async def test_spoken_invoice_keeps_issuer_recipient_and_tax_regime(client: AsyncClient, planned_by_test_model):
    token = await login(client)
    response = await client.post(
        "/chat",
        headers=auth(token),
        json={
            "message": (
                "mi fai una fattura per gadduci di mandoperda i 50000 euro a otil Srl "
                "senza iva con dichiarazione d intento"
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    args = response.json()["tasks"][0]["args"]
    assert args == {
        "account_name": "Andrea Gadducci",
        "client_name": "Otil SRL",
        "description": "Manodopera",
        "net_eur": 50000.0,
        "vat_rate": 0.0,
        "vat_note": "Dichiarazione d'intento",
    }


@pytest.mark.asyncio
async def test_incomplete_invoice_returns_the_structured_chat_draft(client: AsyncClient, planned_by_test_model):
    token = await login(client)
    response = await client.post(
        "/chat",
        headers=auth(token),
        json={"message": "mi fai una fattura per Mario Rossi"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["pending"] == {
        "capability": "invoice_prepare_demo",
        "account_name": "",
        "client_name": "Mario Rossi",
        "description": "",
        "net_eur": None,
        "vat_rate": 0.22,
        "vat_note": "",
    }
    reset = await client.post("/chat/reset", headers=auth(token))
    assert reset.status_code == 200


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
async def test_the_error_counter_shows_today_not_forever(client: AsyncClient):
    """Un errore di ieri resta nella lista, ma non tiene il contatore rosso."""

    token = await login(client)
    async with SessionLocal() as session:
        session.add(
            Task(
                tenant_id=DEMO_TENANT_ID,
                requested_by="22222222-2222-2222-2222-222222222222",
                goal="Lavoro andato male la settimana scorsa",
                capability="visure_prepare",
                args_json="{}",
                risk="medium",
                status="failed",
                error="Quel PC non sa fare questo lavoro.",
                idempotency_key="errore-vecchio",
                created_at=utcnow() - timedelta(days=8),
            )
        )
        session.add(
            Task(
                tenant_id=DEMO_TENANT_ID,
                requested_by="22222222-2222-2222-2222-222222222222",
                goal="Errore tecnico già corretto dall'aggiornamento",
                capability="portal_open",
                args_json="{}",
                result_json=json.dumps({"error_resolved": True}),
                risk="medium",
                status="failed",
                error="Risolto dall'aggiornamento.",
                idempotency_key="errore-recente-risolto",
                created_at=utcnow(),
            )
        )
        await session.commit()

    overview = await client.get("/overview", headers=auth(token))
    assert overview.json()["errors"] == 0
    assert overview.json()["active_errors"] == 0
    assert overview.json()["historical_errors"] >= 1

    tasks = await client.get("/tasks", headers=auth(token))
    stale = [t for t in tasks.json()["tasks"] if t["goal"].startswith("Lavoro andato male")]
    assert stale and stale[0]["status"] == "failed", "l'errore vecchio resta visibile nella lista"
    assert stale[0]["error_state"] == "historical"
    resolved = [t for t in tasks.json()["tasks"] if t["goal"].startswith("Errore tecnico")]
    assert resolved and resolved[0]["error_state"] == "historical"


@pytest.mark.asyncio
async def test_ai_provider_selection_is_persisted_per_studio(client: AsyncClient):
    token = await login(client)
    selected = await client.post(
        "/ai/provider",
        headers=auth(token),
        json={"provider": "ollama"},
    )
    assert selected.status_code == 200
    assert selected.json()["provider"] == "ollama"

    providers = await client.get("/ai/providers", headers=auth(token))
    assert providers.json()["selected"] == "ollama"
    assert {item["provider"] for item in providers.json()["providers"]} == {
        "grok",
        "ollama",
        "openai",
    }

    invalid = await client.post(
        "/ai/provider",
        headers=auth(token),
        json={"provider": "sconosciuto"},
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_owner_saves_grok_key_encrypted_without_returning_it(
    client: AsyncClient,
    monkeypatch,
):
    secret = "xai-test-secret-that-must-never-be-returned"
    monkeypatch.setattr(settings, "kreluna_managed_ai_url", "")

    async def healthy(config, **_kwargs):
        assert config.provider == "grok"
        assert config.model == "grok-4.6"
        assert config.api_key == secret
        return {
            "provider": "grok",
            "label": "Grok",
            "model": "grok-4.6",
            "configured": True,
            "connected": True,
            "status": "connected",
            "detail": "Provider e modello raggiungibili",
        }

    monkeypatch.setattr("app.routers.core.check_ai_health", healthy)
    token = await login(client)
    saved = await client.post(
        "/ai/configure",
        headers=auth(token),
        json={"provider": "grok", "model": "grok-4.6", "api_key": secret},
    )

    assert saved.status_code == 200
    assert saved.json()["connected"] is True
    assert secret not in saved.text
    providers = await client.get("/ai/providers", headers=auth(token))
    assert secret not in providers.text
    grok = next(item for item in providers.json()["providers"] if item["provider"] == "grok")
    assert grok["key_saved"] is True
    assert grok["configured"] is True
    retained = await client.post(
        "/ai/configure",
        headers=auth(token),
        json={"provider": "grok", "model": "grok-4.6", "api_key": ""},
    )
    assert retained.status_code == 200
    assert retained.json()["connected"] is True

    viewer = await login(client, "viewer@studio.demo")
    forbidden = await client.post(
        "/ai/configure",
        headers=auth(viewer),
        json={"provider": "grok", "model": "grok-4.6", "api_key": secret},
    )
    assert forbidden.status_code == 403

    async with SessionLocal() as session:
        stored = await session.get(
            AIProviderCredential,
            {"tenant_id": DEMO_TENANT_ID, "provider": "grok"},
        )
        assert stored is not None
        assert stored.api_key_ciphertext.startswith("v1.")
        assert secret not in stored.api_key_ciphertext


@pytest.mark.asyncio
async def test_owner_activates_managed_ai_with_a_revocable_customer_code(
    client: AsyncClient,
    monkeypatch,
    tmp_path,
):
    activation_code = "kreluna_live_" + "C" * 43
    monkeypatch.setenv("KRELUNA_SUPPORT_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "kreluna_managed_ai_token", "")
    monkeypatch.setattr(settings, "kreluna_grok_api_key", "")

    async def healthy(config, **_kwargs):
        assert config.managed is True
        assert config.api_key == activation_code
        return {
            "provider": "grok",
            "label": "IA Kreluna",
            "model": "grok-4.6",
            "configured": True,
            "connected": True,
            "status": "connected",
            "detail": "Provider e modello raggiungibili",
            "managed": True,
            "configurable": False,
        }

    monkeypatch.setattr("app.routers.core.check_ai_health", healthy)
    token = await login(client)
    activated = await client.post(
        "/ai/activate",
        headers=auth(token),
        json={"activation_code": activation_code},
    )
    assert activated.status_code == 200
    assert activated.json()["connected"] is True
    assert activation_code not in activated.text
    assert (tmp_path / "managed_ai.token").read_text(encoding="utf-8").strip() == activation_code
    assert (tmp_path / "managed_ai.token").stat().st_mode & 0o777 == 0o600

    viewer = await login(client, "viewer@studio.demo")
    forbidden = await client.post(
        "/ai/activate",
        headers=auth(viewer),
        json={"activation_code": activation_code},
    )
    assert forbidden.status_code == 403

@pytest.mark.asyncio
async def test_a_stopped_pc_sends_the_work_back_to_the_queue(client: AsyncClient, planned_by_test_model):
    """Dopo Ferma il lavoro non si perde: torna in coda e riparte con Riprendi."""

    token = await login(client)
    private, device_id, _code = await enroll_test_agent(
        client,
        role=f"pc-ferma-{uuid4()}",
        capabilities=["visure_prepare"],
    )
    planned = await client.post(
        "/chat",
        headers=auth(token),
        json={"message": "Prepara la visura per Verdi Luigi"},
    )
    task_id = planned.json()["tasks"][0]["id"]
    async with SessionLocal() as session:
        task = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        task.assigned_device_id = device_id
        task.status = "assigned"
        await session.commit()

    refused = await client.post(
        "/agent/ingest",
        json=signed_ingest(
            private,
            device_id=device_id,
            task_id=task_id,
            ok=False,
            error="AGENT_KILLED",
        ),
    )
    assert refused.status_code == 200
    assert refused.json()["status"] == "queued"

    async with SessionLocal() as session:
        task = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.status == "queued"
        assert task.assigned_device_id is None
        assert task.error is None

    overview = await client.get("/overview", headers=auth(token))
    assert overview.json()["errors"] == 0


@pytest.mark.asyncio
async def test_approval_token_single_use_and_kill(client: AsyncClient, planned_by_test_model):
    token = await login(client)
    private, device_id, _code = await enroll_test_agent(
        client,
        role=f"pc-approval-{uuid4()}",
        capabilities=["invoice_prepare_demo", "invoice_submit_demo"],
    )
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
        task.status = "assigned"
        await session.commit()

    ingest = await client.post(
        "/agent/ingest",
        json=signed_ingest(
            private,
            device_id=device_id,
            task_id=task_id,
            ok=True,
            result={
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
        ),
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


@pytest.mark.asyncio
async def test_ready_viewer_and_billing(client: AsyncClient, monkeypatch, planned_by_test_model):
    import hashlib
    import hmac
    import json

    ready = await client.get("/ready")
    assert ready.status_code == 200
    health = await client.get("/health")
    assert health.json()["version"]
    manifest = await client.get("/update/manifest")
    assert manifest.status_code == 200
    body = manifest.json()
    from kreluna_shared.crypto import b64d
    from kreluna_shared.update import APP_VERSION, verify_manifest

    assert body["manifest"]["version"] == APP_VERSION
    assert verify_manifest(b64d(health.json()["server_pubkey"]), body["manifest"], body["signature"])

    async def fake_update_status():
        return {
            "state": "available",
            "available": True,
            "current_version": APP_VERSION,
            "latest_version": "9.0.0",
            "notes": "Aggiornamento di prova",
            "download_url": "https://github.com/krelunaid/kreluna-director/releases/latest",
        }

    monkeypatch.setattr("app.routers.core.latest_update_status", fake_update_status)
    update = await client.get("/update/status")
    assert update.status_code == 200
    assert update.json()["latest_version"] == "9.0.0"
    viewer = await login(client, "viewer@studio.demo")
    forbidden_update = await client.post("/update/install", headers=auth(viewer))
    assert forbidden_update.status_code == 403
    denied = await client.post("/chat", headers=auth(viewer), json={"message": "ciao"})
    assert denied.status_code == 403
    body = json.dumps({"id": "evt-1", "type": "invoice.paid", "tenant_id": DEMO_TENANT_ID}).encode()
    sig = hmac.new(settings.director_signing_seed.encode(), body, hashlib.sha256).hexdigest()
    paid = await client.post("/billing/webhook", content=body, headers={"X-Kreluna-Signature": sig})
    assert paid.status_code == 200
    assert paid.json()["state"] == "active"
    again = await client.post("/billing/webhook", content=body, headers={"X-Kreluna-Signature": sig})
    assert again.json().get("duplicate") is True
    fail = json.dumps({"id": "evt-2", "type": "invoice.payment_failed", "tenant_id": DEMO_TENANT_ID}).encode()
    sig2 = hmac.new(settings.director_signing_seed.encode(), fail, hashlib.sha256).hexdigest()
    grace = await client.post("/billing/webhook", content=fail, headers={"X-Kreluna-Signature": sig2})
    assert grace.json()["state"] == "grace"
    owner = await login(client)
    sus = await client.post("/billing/simulate/suspended", headers=auth(owner))
    assert sus.json()["state"] == "suspended"
    blocked = await client.post(
        "/chat", headers=auth(owner), json={"message": "Apri Blocco Note e scrivi CIAO"}
    )
    assert blocked.json()["denied"] is True
    await client.post("/billing/simulate/active", headers=auth(owner))


@pytest.mark.asyncio
async def test_owner_can_start_verified_mac_update(client: AsyncClient, monkeypatch):
    from types import SimpleNamespace

    from app.routers import core
    from kreluna_shared import macos_update

    owner = await login(client)
    seen = {}

    async def fake_update_status(*, force: bool = False):
        assert force is True
        return {
            "available": True,
            "latest_version": "9.0.0",
            "platform": "macos",
            "download_url": "https://github.com/example.zip",
            "checksum_url": "https://github.com/example.zip.sha256",
        }

    def fake_stage(status, *, current_app, support_dir):
        seen.update(status=status, current_app=current_app, support_dir=support_dir)
        return SimpleNamespace(version="9.0.0")

    monkeypatch.setattr(core.sys, "platform", "darwin")
    monkeypatch.setenv("KRELUNA_DESKTOP_APP", "1")
    monkeypatch.setenv("KRELUNA_APP_BUNDLE", "/Applications/Kreluna Director.app")
    monkeypatch.setenv("KRELUNA_SUPPORT_DIR", "/tmp/KrelunaDirector-test")
    monkeypatch.setattr(core, "latest_update_status", fake_update_status)
    monkeypatch.setattr(core, "_schedule_process_exit", lambda: seen.update(exit_scheduled=True))
    monkeypatch.setattr(macos_update, "stage_macos_update", fake_stage)
    monkeypatch.setattr(
        macos_update,
        "launch_macos_update",
        lambda staged, parent_pid: seen.update(parent_pid=parent_pid) or 1234,
    )

    response = await client.post("/update/install", headers=auth(owner))
    assert response.status_code == 200
    assert response.json()["version"] == "9.0.0"
    assert response.json()["state"] == "restarting"
    assert seen["current_app"] == Path("/Applications/Kreluna Director.app")
    assert seen["exit_scheduled"] is True
