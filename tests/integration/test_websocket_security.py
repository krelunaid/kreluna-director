from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient
from kreluna_shared.crypto import (
    agent_challenge_payload,
    b64e,
    generate_device_keypair,
    sign_bytes,
)
from starlette.websockets import WebSocketDisconnect


def test_websockets_require_device_proof_and_dashboard_session():
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "andrea@studio.demo", "password": "demo"},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        issued = client.post(
            "/agents/pc-fatture/enrollment",
            headers={"Authorization": f"Bearer {token}"},
        )
        if issued.status_code == 409:
            agents = client.get(
                "/agents", headers={"Authorization": f"Bearer {token}"}
            ).json()["agents"]
            existing = next(
                item for item in agents if item["agent_id"] == "pc-fatture"
            )
            revoked = client.post(
                f"/devices/{existing['device_id']}/revoke",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert revoked.status_code == 200
            issued = client.post(
                "/agents/pc-fatture/enrollment",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert issued.status_code == 200
        private, public = generate_device_keypair()
        enrolled = client.post(
            "/enrollment/redeem",
            json={
                "enrollment_code": issued.json()["enrollment_code"],
                "agent_id": "pc-fatture",
                "hostname": "mac-firmato",
                "public_key": b64e(public),
                "capabilities": ["invoice_prepare_demo"],
                "platform": "macos",
            },
        )
        assert enrolled.status_code == 200
        device_id = enrolled.json()["device_id"]

        with client.websocket_connect("/ws/agent") as socket:
            challenge = socket.receive_json()["challenge"]
            socket.send_json(
                {
                    "type": "hello",
                    "device_id": device_id,
                    "agent_id": "pc-fatture",
                    "challenge": challenge,
                    "signature": b64e(b"not-a-valid-signature"),
                }
            )
            assert socket.receive_json()["error"] == "AGENT_AUTH_INVALID"
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 4401

        with client.websocket_connect("/ws/agent") as socket:
            challenge = socket.receive_json()["challenge"]
            socket.send_json(
                {
                    "type": "hello",
                    "device_id": device_id,
                    "agent_id": "pc-visure",
                    "challenge": challenge,
                    "signature": b64e(
                        sign_bytes(
                            private,
                            agent_challenge_payload(device_id, "pc-visure", challenge),
                        )
                    ),
                }
            )
            assert socket.receive_json()["error"] == "AGENT_AUTH_INVALID"

        with client.websocket_connect("/ws/agent") as socket:
            challenge = socket.receive_json()["challenge"]
            signature = b64e(
                sign_bytes(
                    private,
                    agent_challenge_payload(device_id, "pc-fatture", challenge),
                )
            )
            socket.send_json(
                {
                    "type": "hello",
                    "device_id": device_id,
                    "agent_id": "pc-fatture",
                    "hostname": "mac-firmato",
                    "capabilities": ["invoice_prepare_demo"],
                    "platform": "macos",
                    "challenge": challenge,
                    "signature": signature,
                }
            )
            assert socket.receive_json()["type"] == "welcome"

        with (
            pytest.raises(WebSocketDisconnect) as denied,
            client.websocket_connect("/ws/dashboard"),
        ):
            pass
        assert denied.value.code == 4401

        with client.websocket_connect(f"/ws/dashboard?token={token}") as dashboard:
            assert dashboard.receive_json() == {"type": "hello", "service": "director"}
