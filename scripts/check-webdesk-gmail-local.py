"""Real Webdesk/Gmail login, isolated in-memory task; never prepares an invoice."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for path in ("apps/director-desktop", "apps/director-api", "apps/kreluna-agent", "packages/kreluna-shared/src"):
    sys.path.insert(0, str(ROOT / path))


async def main():
    from kreluna_desktop import prepare_env
    prepare_env()
    import uvicorn
    from agent.capabilities.portal import open_portal
    from agent.tools import mac_browser
    from app.config import settings
    from app.database import Base, SessionLocal, get_session
    from app.models import (
        ClientCredential,
        Device,
        GmailConnection,
        Task,
        Tenant,
        User,
        WebdeskMailPolicy,
    )
    from app.routers.agent_io import router
    from fastapi import FastAPI
    from kreluna_shared.crypto import agent_http_payload, b64e, generate_device_keypair, sign_bytes
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # Only encrypted rows are copied; the installed database is never changed.
    async with SessionLocal() as installed:
        connections = (await installed.execute(select(GmailConnection))).scalars().all()
        if len(connections) != 1:
            print("REQUIRES_ONE_GMAIL_CONNECTION")
            return 1
        connection = connections[0]
        credentials = (await installed.execute(select(ClientCredential).where(
            ClientCredential.tenant_id == connection.tenant_id, ClientCredential.portal == "webdesk",
            ClientCredential.status == "ready"))).scalars().all()
        if len(credentials) != 1:
            print("REQUIRES_ONE_WEBDESK_ACCOUNT")
            return 1
        credential = credentials[0]
        tenant = await installed.get(Tenant, connection.tenant_id)
        owner = await installed.get(User, connection.updated_by)
        if not tenant or not owner or owner.role != "studio_owner":
            print("OWNER_NOT_AVAILABLE")
            return 1
        def clone(row):
            return type(row)(**{c.name: getattr(row, c.name) for c in row.__table__.columns})
        copies = [clone(row) for row in (tenant, owner, connection, credential)]
        tenant_id, owner_id = tenant.id, owner.id
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    private, public = generate_device_keypair()
    device_id, task_id = str(uuid4()), str(uuid4())
    async with sessions() as session:
        session.add_all(copies)
        session.add(WebdeskMailPolicy(tenant_id=tenant_id, enabled=True, updated_by=owner_id))
        session.add(Device(id=device_id, tenant_id=tenant_id, agent_id="isolated-login-check",
            hostname="local-check", public_key=b64e(public), fingerprint="ephemeral"))
        session.add(Task(id=task_id, tenant_id=tenant_id, requested_by=owner_id, goal="Verify login only",
            capability="portal_open", status="running", assigned_device_id=device_id,
            idempotency_key=task_id, args_json=json.dumps({"portal":"fatture-webdesk",
                "query":credential.client_name, "use_saved_access":True})))
        await session.commit()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(router)
    async def dependency():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_session] = dependency
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    settings.director_public_url = url
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    def sign(path, payload):
        envelope = {**payload, "sent_at":int(time.time()), "nonce":uuid4().hex}
        return {**envelope, "signature":b64e(sign_bytes(private, agent_http_payload(path, envelope)))}
    class NoEvidence(mac_browser.Runner):
        def screencapture(self, path):
            raise mac_browser.MacControlError("Evidence disabled during login verification")
    try:
        for _ in range(100):
            if server.started: break
            await asyncio.sleep(0.05)
        if not server.started:
            print("LOCAL_CHECK_NOT_STARTED")
            return 1
        print("REAL_WEBDESK_LOGIN_CHECK_STARTED_NO_INVOICE_ACTIONS", flush=True)
        dedicated = "--dedicated" in sys.argv
        if dedicated:
            os.environ["KRELUNA_WEBDESK_BROWSER"] = "dedicated"
        result = await asyncio.to_thread(open_portal, portal="fatture-webdesk", query="",
            use_saved_access=True, director_url=url, device_id=device_id, task_id=task_id,
            sign_request=sign, runner=None if dedicated else NoEvidence())
        # A stopped login is not success, even if legacy portal result says ok.
        success = result.get("message", "").startswith("Accesso a Webdesk completato.")
        print("REAL_WEBDESK_LOGIN_VERIFIED" if success else "REAL_WEBDESK_LOGIN_NOT_COMPLETED", flush=True)
        return 0 if success else 1
    except Exception as exc:  # noqa: BLE001 -- Only the type, never credentials or scripts.
        print("REAL_WEBDESK_LOGIN_CHECK_STOPPED_NO_SECRETS_LOGGED", flush=True)
        print("FAILURE_TYPE=" + type(exc).__name__, flush=True)
        if getattr(exc, "validation_stage", "") in {"unknown", "other", "request", "code", "changed"}:
            print("VALIDATION_STAGE=" + exc.validation_stage, flush=True)
            print("RECIPIENT_MATCHES=" + str(exc.recipient_matches), flush=True)
        diagnostic = getattr(exc, "diagnostic", "")
        if diagnostic in {"NAVIGATION_IN_PROGRESS", "PAGE_OPERATION_FAILED"}:
            print("FAILURE_REASON=" + diagnostic, flush=True)
        print("FAILURE_FRAMES=" + ",".join(
            f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)
        ), flush=True)
        from agent.tools import dedicated_browser
        service = dedicated_browser._service
        if service is not None:
            def page_diagnostic():
                if service.context is None or not service.context.pages:
                    return "NO_PAGE"
                service.context.pages[-1].wait_for_timeout(10000)
                if "--inspect-failure" in sys.argv:
                    shot = Path(tempfile.mkdtemp(prefix="kreluna-browser-check-")) / "page.png"
                    page = service.context.pages[-1]
                    page.screenshot(path=str(shot), mask=[page.locator("input")])
                    print("LOCAL_DIAGNOSTIC_IMAGE=" + str(shot), flush=True)
                return service.context.pages[-1].evaluate("""(() => ({
                  host:location.hostname,path:location.pathname,
                  validation:document.body.innerText.includes('Validazione della postazione'),
                  emailCount:(document.body.innerText.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/g)||[]).length,
                  field:!!document.getElementById('MainContent_CodSicurezza'),
                  confirm:!!document.getElementById('MainContent_ChangePasswordPushButton'),
                  confirmDisabled:document.getElementById('MainContent_ChangePasswordPushButton')?.disabled,
                  confirmLabel:document.getElementById('MainContent_ChangePasswordPushButton')?.value,
                  validated:!!document.getElementById('MainContent_VaiWebdesLink'),
                  request:document.body.innerText.includes('Invia codice di sicurezza')
                  ,fields:Array.from(document.querySelectorAll('input')).map(e=>({id:e.id,type:e.type}))
                  ,buttons:Array.from(document.querySelectorAll('button')).map(e=>({id:e.id}))
                }))()""")
            try:
                print("PAGE_CHECK=" + json.dumps(service.executor.submit(page_diagnostic).result(timeout=25)), flush=True)
            except Exception:  # noqa: BLE001, S110 -- no page contents in failure logs.
                pass
        return 1
    finally:
        from agent.tools.dedicated_browser import shutdown
        await asyncio.to_thread(shutdown)
        server.should_exit = True
        await serving
        listener.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
