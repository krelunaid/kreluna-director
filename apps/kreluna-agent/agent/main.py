from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
from pathlib import Path
from uuid import UUID

import httpx
import websockets

from agent.capabilities import CAPABILITY_ALLOWLIST
from agent.identity import AgentIdentity
from agent.safety import SafetyState
from kreluna_shared.agents import capabilities_for_role
from kreluna_shared.crypto import b64d, b64e, sign_bytes, verify_grant

ROOT = Path(__file__).resolve().parents[3]


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class AgentApp:
    def __init__(self) -> None:
        data_dir = Path(env("KRELUNA_AGENT_DATA_DIR", str(ROOT / "data" / "agent")))
        self.identity = AgentIdentity(
            data_dir,
            env("KRELUNA_AGENT_ID", "pc-fatture"),
            env("KRELUNA_AGENT_DISPLAY_NAME", "PC-FATTURE"),
        )
        self.director = env("AGENT_DIRECTOR_URL", "http://127.0.0.1:8080").rstrip("/")
        self.wss = env("AGENT_DIRECTOR_WSS", "ws://127.0.0.1:8080/ws/agent")
        self.enroll_code = env("KRELUNA_ENROLLMENT_CODE", "KRELUNA-DEV-ENROLL")
        self.safety = SafetyState()
        self.server_pubkey: bytes | None = None
        self.used_nonces: set[str] = set()
        self.role_caps = capabilities_for_role(self.identity.agent_id) or list(CAPABILITY_ALLOWLIST)

    async def start(self) -> None:
        async with httpx.AsyncClient() as client:
            await self.ensure_enrolled(client)
            health = (await client.get(f"{self.director}/health")).json()
            self.server_pubkey = b64d(health["server_pubkey"])
        await self.loop()

    async def ensure_enrolled(self, client: httpx.AsyncClient) -> None:
        if self.identity.device_id:
            return
        response = await client.post(
            f"{self.director}/enrollment/redeem",
            json={
                "enrollment_code": self.enroll_code,
                "agent_id": self.identity.agent_id,
                "hostname": self.identity.hostname,
                "public_key": self.identity.public_key_b64(),
                "display_name": self.identity.display_name,
                "capabilities": self.role_caps,
                "platform": self.identity.platform,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        self.identity.save_enrollment(data["device_id"], data["tenant_id"])

    async def loop(self) -> None:
        while True:
            try:
                await self.session()
            except Exception as exc:
                print(f"[kreluna-agent] reconnect in 2s: {exc}", flush=True)
                await asyncio.sleep(2)

    async def session(self) -> None:
        async with websockets.connect(self.wss, ping_interval=10, ping_timeout=10) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "device_id": self.identity.device_id,
                        "agent_id": self.identity.agent_id,
                        "hostname": self.identity.hostname,
                        "display_name": self.identity.display_name,
                        "capabilities": self.role_caps,
                        "platform": self.identity.platform,
                    }
                )
            )
            print(f"[kreluna-agent] connected as {self.identity.device_id}", flush=True)
            consumer = asyncio.create_task(self.consume(ws))
            beat = asyncio.create_task(self.heartbeat(ws))
            done, pending = await asyncio.wait({consumer, beat}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    async def heartbeat(self, ws) -> None:
        while True:
            await ws.send(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "busy": self.safety.active_task_id is not None,
                        "active_task_id": self.safety.active_task_id,
                    }
                )
            )
            await asyncio.sleep(5)

    async def consume(self, ws) -> None:
        async for raw in ws:
            message = json.loads(raw)
            msg_type = message.get("type")
            if msg_type == "kill":
                self.safety.killed = True
                self.safety.active_task_id = None
                await ws.send(json.dumps({"type": "killed", "device_id": self.identity.device_id}))
                print("[kreluna-agent] KILLED", flush=True)
            elif msg_type == "pause":
                self.safety.paused = True
            elif msg_type == "resume":
                self.safety.killed = False
                self.safety.paused = False
                print("[kreluna-agent] RESUMED", flush=True)
            elif msg_type == "task":
                asyncio.create_task(self.run_task(message))

    async def run_task(self, message: dict) -> None:
        task_id = message["task_id"]
        capability = message["capability"]
        try:
            self.safety.assert_not_killed()
            if not self.identity.device_id or self.server_pubkey is None:
                raise PermissionError("NOT_READY")
            verify_grant(
                self.server_pubkey,
                message["grant"],
                expected_task=UUID(task_id),
                expected_device=UUID(self.identity.device_id),
                expected_capability=capability,
                consumed_nonces=self.used_nonces,
            )
            grant_nonce = json.loads(b64d(message["grant"].split(".", 1)[0]))["nonce"]
            self.used_nonces.add(grant_nonce)
            handler = CAPABILITY_ALLOWLIST.get(capability)
            if handler is None or capability not in self.role_caps:
                raise PermissionError("CAPABILITY_NOT_ALLOWED")
            self.safety.active_task_id = task_id
            args = dict(message.get("args") or {})
            async with self.safety.gui_lock:
                result = await self._invoke(handler, args, task_id)
            await self.report(task_id, True, result, None)
        except Exception as exc:
            await self.report(task_id, False, {}, str(exc))
        finally:
            self.safety.active_task_id = None

    async def _invoke(self, handler, args: dict, task_id: str):
        signature = b64e(sign_bytes(self.identity.private_key, task_id.encode()))
        extra = {
            "client": httpx.AsyncClient(),
            "director_url": self.director,
            "device_id": self.identity.device_id,
            "task_id": task_id,
            "signature": signature,
        }
        try:
            accepted = set(inspect.signature(handler).parameters)
            call_args = {key: value for key, value in {**args, **extra}.items() if key in accepted}
            outcome = handler(**call_args)
            if inspect.isawaitable(outcome):
                return await outcome
            return outcome
        finally:
            await extra["client"].aclose()

    async def report(self, task_id: str, ok: bool, result: dict, error: str | None) -> None:
        evidence = []
        clean_result = dict(result)
        for item in clean_result.pop("evidence", []) or []:
            png = item.pop("png", None)
            evidence.append(
                {
                    "kind": item.get("kind", "screenshot"),
                    "sha256": item["sha256"],
                    "png_b64": base64.b64encode(png).decode("ascii") if png else None,
                    "metadata": item.get("metadata") or {},
                }
            )
        signature = b64e(sign_bytes(self.identity.private_key, task_id.encode()))
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.director}/agent/ingest",
                json={
                    "device_id": self.identity.device_id,
                    "task_id": task_id,
                    "signature": signature,
                    "ok": ok,
                    "result": clean_result,
                    "error": error,
                    "evidence": evidence,
                },
                timeout=30,
            )
            response.raise_for_status()
        print(f"[kreluna-agent] task {task_id} -> {'ok' if ok else error}", flush=True)


def identity() -> dict:
    agent_id = env("KRELUNA_AGENT_ID") or "auto"
    return AgentIdentity(Path(env("KRELUNA_AGENT_DATA_DIR", str(ROOT / "data" / "agent"))), agent_id, "local").as_hello()


if __name__ == "__main__":
    if os.getenv("KRELUNA_AGENT_PRINT_IDENTITY") == "1":
        print(json.dumps(identity()))
    else:
        asyncio.run(AgentApp().start())
