import asyncio
import time

import pytest

from agent.remote_control import RemoteControl
from agent.safety import SafetyState
from app.services import remote_control as relay


@pytest.mark.asyncio
async def test_remote_lease_guards_and_input(monkeypatch):
    monkeypatch.setattr('agent.remote_control.capture', lambda: ('jpeg', (1000, 700)))
    inputs = []
    monkeypatch.setattr('agent.remote_control.input_event', lambda body, size: inputs.append(body['action']))
    safety = SafetyState()
    remote = RemoteControl(safety)
    frame = await remote.execute({'action': 'start', 'owner': 'a'})
    assert frame['ok'] and safety.remote_active
    with pytest.raises(PermissionError):
        safety.assert_not_killed()
    body = {'owner': 'a', 'session_id': frame['session_id'], 'frame_id': frame['frame_id']}
    assert not (await remote.execute({**body, 'action': 'click'}))['ok']
    assert not (await remote.execute({**body, 'owner': 'b', 'action': 'control'}))['ok']
    assert (await remote.execute({**body, 'action': 'control'}))['ok']
    assert (await remote.execute({**body, 'action': 'click', 'x': .5, 'y': .5}))['ok']
    assert not (await remote.execute({**body, 'action': 'click'}))['ok']
    assert inputs == ['click']
    remote.until = time.monotonic() - 1
    remote.expire()
    assert not safety.remote_active
    assert not (await remote.execute({**body, 'action': 'text', 'text': 'example'}))['ok']


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('active_task_id', 'task'), ('workers', 1), ('killed', True)])
async def test_remote_never_interrupts_worker(field, value):
    safety = SafetyState()
    setattr(safety, field, value)
    remote = RemoteControl(safety)
    assert not (await remote.execute({'action': 'start', 'owner': 'a'}))['ok']
    assert not safety.remote_active


@pytest.mark.asyncio
async def test_capture_failure_releases_session(monkeypatch):
    def fail():
        raise OSError('private detail')
    monkeypatch.setattr('agent.remote_control.capture', fail)
    safety = SafetyState()
    result = await RemoteControl(safety).execute({'action': 'start', 'owner': 'a'})
    assert not result['ok'] and 'private detail' not in result['error']
    assert not safety.remote_active


@pytest.mark.asyncio
async def test_reply_is_bound_to_original_device_and_socket():
    future = asyncio.get_running_loop().create_future()
    socket = object()
    relay.pending['request'] = ('device', socket, future)
    try:
        message = {'request_id': 'request', 'result': {'ok': True}}
        relay.reply('another-device', socket, message)
        relay.reply('device', object(), message)
        assert not future.done()
        relay.reply('device', socket, message)
        assert future.result() == {'ok': True}
    finally:
        relay.pending.pop('request')
