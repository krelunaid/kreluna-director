from __future__ import annotations

import json
import stat

import pytest
from app.config import settings
from app.middleware.remote_agent_only import RemoteAgentOnlyMiddleware
from app.services.remote_access import (
    RemoteTunnelManager,
    validate_public_url,
    validate_tunnel_token,
)

VALID_TOKEN = "A" * 100


def test_remote_url_requires_public_https() -> None:
    assert validate_public_url("https://director.studio.example/") == "https://director.studio.example"
    for value in (
        "http://director.studio.example",
        "https://localhost",
        "https://user:pass@director.studio.example",
        "https://director.studio.example/dashboard",
    ):
        with pytest.raises(ValueError):
            validate_public_url(value)


def test_tunnel_token_is_strict_and_never_returned(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "director_remote_dir", str(tmp_path))
    monkeypatch.setattr(settings, "director_public_url", settings.director_public_url)
    manager = RemoteTunnelManager()
    saved = manager.save("https://director.studio.example", VALID_TOKEN)

    assert saved.token == VALID_TOKEN
    assert manager.load() == saved
    assert json.loads((tmp_path / "remote-link.json").read_text())["public_url"] == saved.public_url
    assert (tmp_path / "remote-tunnel.token").read_text().strip() == VALID_TOKEN
    assert stat.S_IMODE((tmp_path / "remote-tunnel.token").stat().st_mode) == 0o600
    assert VALID_TOKEN not in json.dumps(manager.status())


def test_tunnel_token_rejects_whitespace() -> None:
    with pytest.raises(ValueError):
        validate_tunnel_token("A" * 90 + " secret")


@pytest.mark.asyncio
async def test_public_tunnel_exposes_only_agent_paths(monkeypatch) -> None:
    calls: list[str] = []

    async def downstream(scope, _receive, send) -> None:
        calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(
        "app.middleware.remote_agent_only.remote_tunnel.public_hostname",
        lambda: "director.studio.example",
    )
    middleware = RemoteAgentOnlyMiddleware(downstream)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run(path: str) -> list[dict]:
        sent: list[dict] = []

        async def send(message: dict) -> None:
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "path": path,
                "headers": [(b"host", b"director.studio.example")],
            },
            receive,
            send,
        )
        return sent

    blocked = await run("/auth/login")
    allowed = await run("/agent/ingest")

    assert blocked[0]["status"] == 404
    assert allowed[0]["status"] == 200
    assert calls == ["/agent/ingest"]
