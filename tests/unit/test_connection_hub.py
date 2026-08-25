import pytest
from app.services.registry import ConnectionHub


@pytest.mark.asyncio
async def test_old_socket_cannot_remove_a_new_reconnection():
    hub = ConnectionHub()
    old_socket = object()
    new_socket = object()

    await hub.register_agent("device-1", "tenant-1", old_socket)
    await hub.register_agent("device-1", "tenant-1", new_socket)
    hub.drop_agent("device-1", old_socket)

    assert hub.agents["device-1"] is new_socket
    hub.drop_agent("device-1", new_socket)
    assert "device-1" not in hub.agents


class RecordingSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_agent_and_dashboard_broadcasts_are_tenant_isolated():
    hub = ConnectionHub()
    first_agent = RecordingSocket()
    second_agent = RecordingSocket()
    first_dashboard = RecordingSocket()
    second_dashboard = RecordingSocket()

    await hub.register_agent("device-1", "tenant-1", first_agent)
    await hub.register_agent("device-2", "tenant-2", second_agent)
    hub.register_dashboard("tenant-1", first_dashboard)
    hub.register_dashboard("tenant-2", second_dashboard)

    assert await hub.broadcast_agents("tenant-1", {"type": "kill"}) == 1
    await hub.broadcast_dashboard("tenant-1", {"type": "refresh"})

    assert first_agent.messages == [{"type": "kill"}]
    assert second_agent.messages == []
    assert first_dashboard.messages == [{"type": "refresh"}]
    assert second_dashboard.messages == []
