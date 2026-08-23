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
from app.routers.ws import router as ws_router
from app.seed import seed_if_empty
from app.database import SessionLocal


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.evidence_path.mkdir(parents=True, exist_ok=True)
    Path(ROOT / "data").mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_if_empty(session)
    yield


app = FastAPI(title="Kreluna Director", version="0.2.0", lifespan=lifespan)
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
app.include_router(ws_router)

web_dist = ROOT / "apps" / "director-web" / "dist"
if web_dist.exists():
    assets = web_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    async def spa_index():
        return FileResponse(web_dist / "index.html")
else:

    @app.get("/")
    async def root():
        return {"ok": True, "service": "director-api", "ui": "not-built"}
