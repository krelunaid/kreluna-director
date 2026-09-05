import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agent.main import AgentApp
from agent.safety import SafetyState
from kreluna_shared.crypto import generate_device_keypair


def agent_without_network() -> AgentApp:
    app = AgentApp.__new__(AgentApp)
    private, _ = generate_device_keypair()
    app.identity = SimpleNamespace(private_key=private, device_id=str(uuid4()))
    app.director = "http://127.0.0.1:8080"
    app.safety = SafetyState()
    return app


class OwnedProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True


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

    async def handler(client, director_url, device_id, task_id, sign_request) -> dict:
        assert client is not None
        assert director_url.startswith("http")
        assert device_id and task_id
        assert sign_request("/agent/test", {"device_id": device_id})["signature"]
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


def test_kill_and_task_cancel_stop_owned_ui_processes():
    safety = SafetyState()
    killed_process = OwnedProcess()
    safety.register_process(killed_process)
    safety.begin_task("task-1")

    safety.kill()

    assert killed_process.terminated is True
    with pytest.raises(PermissionError, match="AGENT_KILLED"):
        safety.assert_task_active("task-1")

    safety.resume()
    cancelled_process = OwnedProcess()
    safety.register_process(cancelled_process)
    safety.cancel_task("task-2")

    assert cancelled_process.terminated is True
    with pytest.raises(PermissionError, match="TASK_CANCELLED"):
        safety.assert_task_active("task-2")


@pytest.mark.asyncio
async def test_agent_waits_for_director_instead_of_exiting(monkeypatch):
    app = agent_without_network()
    app.server_pubkey = None
    app.ensure_enrolled = lambda client: asyncio.sleep(0)
    attempts = 0

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("Director in avvio")
            return httpx.Response(
                200,
                request=httpx.Request("GET", app.director + "/health"),
                json={"server_pubkey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="},
            )

    async def stop_after_bootstrap():
        raise asyncio.CancelledError

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    app.loop = stop_after_bootstrap

    with pytest.raises(asyncio.CancelledError):
        await app.start()

    assert attempts == 2
    assert app.server_pubkey is not None
