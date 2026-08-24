from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT, settings
from app.database import Base, engine
from app.routers.agent_io import router as agent_io_router
from app.routers.core import router as core_router
from app.routers.work import router as work_router
from app.routers.billing import router as billing_router
from app.routers.ws import router as ws_router
from app.seed import seed_if_empty
from app.database import SessionLocal
from kreluna_shared.update import APP_VERSION


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.evidence_path.mkdir(parents=True, exist_ok=True)
    Path(ROOT / "data").mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_if_empty(session)
    yield


app = FastAPI(title="Kreluna Director", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(core_router)
app.include_router(work_router)
app.include_router(agent_io_router)
app.include_router(billing_router)
app.include_router(ws_router)

def _web_dist() -> Path:
    return ROOT / "apps" / "director-web" / "dist"


web_dist = _web_dist()
if web_dist.exists() and (web_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")


@app.get("/")
async def spa_index():
    index = _web_dist() / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"ok": True, "service": "director-api", "ui": "not-built"}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    reserved = {
        "health",
        "auth",
        "me",
        "chat",
        "tasks",
        "agents",
        "devices",
        "approvals",
        "evidence",
        "audit",
        "overview",
        "kill-switch",
        "policy",
        "ws",
        "agent",
        "demo",
        "billing",
        "ready",
        "update",
        "docs",
        "redoc",
        "openapi.json",
        "assets",
    }
    head = full_path.split("/", 1)[0]
    if head in reserved:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Non trovato")
    dist = _web_dist()
    if not dist.exists():
        return {"ok": False, "error": "ui-not-built", "path": full_path}
    candidate = dist / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    index = dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"ok": False, "error": "ui-not-built", "path": full_path}
