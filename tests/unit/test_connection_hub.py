import pytest
from app.services.registry import ConnectionHub


@pytest.mark.asyncio
async def test_old_socket_cannot_remove_a_new_reconnection():
    hub = ConnectionHub()
    old_socket = object()
    new_socket = object()

    await hub.register_agent("device-1", old_socket)
    await hub.register_agent("device-1", new_socket)
    hub.drop_agent("device-1", old_socket)

    assert hub.agents["device-1"] is new_socket
    hub.drop_agent("device-1", new_socket)
    assert "device-1" not in hub.agents
