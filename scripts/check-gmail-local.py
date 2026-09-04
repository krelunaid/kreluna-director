"""Owner-run local OAuth check. Does not start the Director job queue or any Agent."""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in ("apps/director-desktop", "apps/director-api", "packages/kreluna-shared/src"):
    sys.path.insert(0, str(ROOT / path))


async def run(email: str) -> int:
    from kreluna_desktop import SUPPORT, prepare_env

    if not (SUPPORT / "data" / "kreluna.db").is_file() or not (SUPPORT / "gmail-oauth-client.json").is_file():
        print("Manca l’installazione Director o il client Google locale.")
        return 1
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    os.environ["DIRECTOR_PORT"] = str(listener.getsockname()[1])
    prepare_env()
    import uvicorn
    from app.config import settings
    from app.database import SessionLocal, engine
    from app.deps import Actor
    from app.models import GmailAuthorization, GmailConnection, User
    from app.services.gmail import (
        GmailError,
        begin_authorization,
        complete_authorization,
        verify_connection,
    )
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from sqlalchemy import select

    async with engine.begin() as connection:
        for model in (GmailConnection, GmailAuthorization):
            await connection.run_sync(lambda conn, table=model.__table__: table.create(conn, checkfirst=True))
    async with SessionLocal() as session:
        owners = (await session.execute(select(User).where(User.role == "studio_owner"))).scalars().all()
        if len(owners) != 1:
            print("La prova locale richiede un solo titolare; usa il collegamento autenticato nell’app.")
            listener.close()
            return 1
        owner = owners[0]
        actor = Actor(owner.id, owner.tenant_id, owner.role, owner.name, owner.email, "active")
        existing = await session.get(GmailConnection, actor.tenant_id)
        if existing is not None:
            if existing.email != email.strip().lower():
                listener.close()
                print("Un altro account Gmail è già collegato. Scollegalo dalle Impostazioni prima di sostituirlo.")
                return 1
            try:
                await verify_connection(session, settings, actor.tenant_id)
            except GmailError:
                listener.close()
                print("Collegamento esistente non verificato. Controlla le Impostazioni prima di ricollegare.")
                return 1
            listener.close()
            print("GMAIL_EXISTING_CONNECTION_REFRESH_VERIFIED_NO_CONSENT", flush=True)
            return 0
        url = await begin_authorization(session, settings, actor, email)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    finished = asyncio.Event()
    successful = False

    @app.get("/integrations/gmail/callback")
    async def callback(request: Request):
        nonlocal successful
        params = request.query_params
        request.scope["query_string"] = b""
        message = "Collegamento non completato. Torna a Kreluna."
        try:
            async with SessionLocal() as session:
                await complete_authorization(session, settings, params.get("state", ""), params.get("code", ""))
                await verify_connection(session, settings, actor.tenant_id)
            successful = True
            message = "Gmail collegato: rinnovo dell’accesso verificato. Nessuna fattura salvata o inviata."
        except GmailError as exc:
            message = str(exc)
        finally:
            finished.set()
        from html import escape
        return HTMLResponse("<!doctype html><meta charset='utf-8'><title>Kreluna Director</title><h1>Kreluna Director</h1><p>" + escape(message) + "</p>",
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                     "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})

    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started or task.done():
                break
            await asyncio.sleep(0.05)
        if not server.started:
            print("Impossibile avviare il ritorno locale Google.")
            return 1
        if sys.platform == "darwin":
            await asyncio.to_thread(subprocess.run, ["open", "-a", "Safari", url], check=True)
        else:
            webbrowser.open(url)
        print("Autorizzazione Google aperta nel browser. In attesa del completamento (5 minuti).", flush=True)
        await asyncio.wait_for(finished.wait(), timeout=300)
        print("GMAIL_CONNECTED_AND_REFRESH_VERIFIED" if successful else "GMAIL_CONNECTION_NOT_COMPLETED", flush=True)
        return 0 if successful else 1
    except TimeoutError:
        print("Autorizzazione non completata entro 5 minuti.", flush=True)
        return 1
    finally:
        server.should_exit = True
        await task
        listener.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments.email)))
