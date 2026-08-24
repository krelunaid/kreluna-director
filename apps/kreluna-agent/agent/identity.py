from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

from kreluna_shared.crypto import b64e, generate_device_keypair


class AgentIdentity:
    def __init__(self, data_dir: Path, agent_id: str, display_name: str):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id
        self.display_name = display_name
        self.hostname = socket.gethostname()
        if sys.platform == "darwin":
            self.platform = "macos"
        elif os.name == "nt":
            self.platform = "windows"
        else:
            self.platform = "linux"
        self.private_key, self.public_key = self._load_or_create_keys()
        self.device_id: str | None = self._read_state().get("device_id")
        self.tenant_id: str | None = self._read_state().get("tenant_id")

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "device.key"

    def _load_or_create_keys(self) -> tuple[bytes, bytes]:
        if self.key_path.exists():
            private = self.key_path.read_bytes()
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization

            public = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return private, public
        private, public = generate_device_keypair()
        self.key_path.write_bytes(private)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return private, public

    def _read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_enrollment(self, device_id: str, tenant_id: str) -> None:
        self.device_id = device_id
        self.tenant_id = tenant_id
        self.state_path.write_text(
            json.dumps({"device_id": device_id, "tenant_id": tenant_id, "agent_id": self.agent_id}, indent=2),
            encoding="utf-8",
        )

    def public_key_b64(self) -> str:
        return b64e(self.public_key)

    def as_hello(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "hostname": self.hostname,
            "platform": self.platform,
            "display_name": self.display_name,
            "device_id": self.device_id,
        }
