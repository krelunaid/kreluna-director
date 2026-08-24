import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent.main import AgentApp
from kreluna_shared.crypto import generate_device_keypair


def agent_without_network() -> AgentApp:
    app = AgentApp.__new__(AgentApp)
    private, _ = generate_device_keypair()
    app.identity = SimpleNamespace(private_key=private, device_id=str(uuid4()))
    app.director = "http://127.0.0.1:8080"
    return app


@pytest.mark.asyncio
async def test_slow_screen_work_does_not_stop_the_heartbeat():
    """Un passo lento sul portale non deve far sembrare il PC spento."""

    app = agent_without_network()
    beats = 0

    async def heartbeat() -> None:
        nonlocal beats
        while True:
            beats += 1
            await asyncio.sleep(0.01)

    def slow_handler() -> dict:
        time.sleep(0.3)
        return {"ok": True}

    beating = asyncio.create_task(heartbeat())
    result = await app._invoke(slow_handler, {}, str(uuid4()))
    beating.cancel()

    assert result == {"ok": True}
    assert beats > 5, f"il battito si è fermato durante il lavoro: {beats}"


@pytest.mark.asyncio
async def test_async_handlers_still_work():
    app = agent_without_network()

    async def handler(client, director_url, device_id, task_id, signature) -> dict:
        assert client is not None
        assert director_url.startswith("http")
        assert device_id and task_id and signature
        return {"ok": True, "async": True}

    result = await app._invoke(handler, {}, str(uuid4()))
    assert result["async"] is True


@pytest.mark.asyncio
async def test_handler_only_gets_the_arguments_it_declares():
    app = agent_without_network()

    def handler(client_name: str = "") -> dict:
        return {"ok": True, "client_name": client_name}

    result = await app._invoke(handler, {"client_name": "Andrea Gadducci", "roba_in_piu": 1}, str(uuid4()))
    assert result["client_name"] == "Andrea Gadducci"
