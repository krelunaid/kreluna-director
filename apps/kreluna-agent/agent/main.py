from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID

import httpx
import websockets
from kreluna_shared.agents import capabilities_for_role
from kreluna_shared.crypto import (
    agent_challenge_payload,
    agent_http_payload,
    b64d,
    b64e,
    canonical_json_bytes,
    sign_bytes,
    verify_grant,
)

from agent.capabilities import CAPABILITY_ALLOWLIST
from agent.identity import AgentIdentity
from agent.safety import SafetyState
from agent.remote_control import RemoteControl

ROOT = Path(__file__).resolve().parents[3]


class EnrollmentRejectedError(ConnectionError):
    pass


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
        enrollment_path = env("KRELUNA_ENROLLMENT_CODE_FILE")
        self.enroll_code_path = Path(enrollment_path) if enrollment_path else None
        self.enroll_code = env("KRELUNA_ENROLLMENT_CODE") or self._read_enrollment_code()
        self.safety = SafetyState()
        self.remote_control = RemoteControl(self.safety)
        self.server_pubkey: bytes | None = None
        self.used_nonces: set[str] = set()
        self.task_jobs: dict[str, asyncio.Task] = {}
        self.role_caps = capabilities_for_role(self.identity.agent_id)
        if not self.role_caps:
            self.role_caps = ["notepad_write"]

    async def start(self) -> None:
        # Il Director e l'Agent possono partire insieme all'accesso dell'utente.
        # Se il servizio locale impiega qualche secondo in piu, l'Agent deve
        # restare vivo e riprovare: una persona non deve riaprirlo a mano.
        while self.server_pubkey is None:
            try:
                async with httpx.AsyncClient() as client:
                    await self.ensure_enrolled(client)
                    response = await client.get(f"{self.director}/health", timeout=10)
                    response.raise_for_status()
                    self.server_pubkey = b64d(response.json()["server_pubkey"])
            except Exception as exc:
                print(f"[kreluna-agent] Director non ancora pronto, riprovo tra 2s: {exc}", flush=True)
                await asyncio.sleep(2)
        try:
            await self.loop()
        finally:
            from agent.tools.dedicated_browser import shutdown

            await asyncio.to_thread(shutdown)

    async def ensure_enrolled(self, client: httpx.AsyncClient) -> None:
        if self.identity.device_id:
            self._discard_enrollment_code()
            return
        if not self.enroll_code:
            raise RuntimeError("Serve un nuovo codice monouso generato dal Director")
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
        self._discard_enrollment_code()

    def _read_enrollment_code(self) -> str:
        if self.enroll_code_path is None:
            return ""
        try:
            return self.enroll_code_path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            return ""

    def _discard_enrollment_code(self) -> None:
        self.enroll_code = ""
        os.environ.pop("KRELUNA_ENROLLMENT_CODE", None)
        if self.enroll_code_path is not None:
            try:
                self.enroll_code_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def loop(self) -> None:
        while True:
            try:
                await self.session()
            except EnrollmentRejectedError:
                print("[kreluna-agent] identità scaduta: nuova registrazione", flush=True)
                self.identity.clear_enrollment()
                try:
                    async with httpx.AsyncClient() as client:
                        await self.ensure_enrolled(client)
                        health = (await client.get(f"{self.director}/health")).json()
                        self.server_pubkey = b64d(health["server_pubkey"])
                except Exception as exc:
                    print(f"[kreluna-agent] registrazione tra 2s: {exc}", flush=True)
                    await asyncio.sleep(2)
            except Exception as exc:
                print(f"[kreluna-agent] reconnect in 2s: {exc}", flush=True)
                await asyncio.sleep(2)

    async def session(self) -> None:
        async with websockets.connect(self.wss, ping_interval=10, ping_timeout=10) as ws:
            challenge_message = json.loads(await ws.recv())
            if challenge_message.get("type") != "challenge":
                raise EnrollmentRejectedError("Il Director non ha autenticato la connessione")
            challenge = str(challenge_message.get("challenge") or "")
            if not challenge:
                raise EnrollmentRejectedError("Challenge Agent mancante")
            signature = b64e(
                sign_bytes(
                    self.identity.private_key,
                    agent_challenge_payload(
                        str(self.identity.device_id),
                        self.identity.agent_id,
                        challenge,
                    ),
                )
            )
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
                        "challenge": challenge,
                        "signature": signature,
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
            self.remote_control.expire()
            await ws.send(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "busy": self.safety.active_task_id is not None or self.safety.remote_active,
                        "active_task_id": self.safety.active_task_id,
                    }
                )
            )
            await asyncio.sleep(5)

    async def consume(self, ws) -> None:
        async for raw in ws:
            message = json.loads(raw)
            msg_type = message.get("type")
            if msg_type == "remote_control":
                result = await self.remote_control.execute(message)
                await ws.send(json.dumps({"type": "remote_control_reply", "request_id": message.get("request_id"), "result": result}))
            elif msg_type == "kill":
                self.remote_control.close()
                active_task_id = self.safety.active_task_id
                self.safety.kill()
                self._cancel_jobs()
                await ws.send(
                    json.dumps(
                        {
                            "type": "killed",
                            "device_id": self.identity.device_id,
                            "active_task_id": active_task_id,
                        }
                    )
                )
                print("[kreluna-agent] KILLED", flush=True)
            elif msg_type == "pause":
                self.safety.pause()
                self._cancel_jobs()
            elif msg_type == "resume":
                self.safety.resume()
                print("[kreluna-agent] RESUMED", flush=True)
            elif msg_type == "task":
                task_id = str(message.get("task_id") or "")
                if task_id and task_id not in self.task_jobs:
                    job = asyncio.create_task(self.run_task(message))
                    self.task_jobs[task_id] = job
                    job.add_done_callback(lambda _job, key=task_id: self.task_jobs.pop(key, None))
            elif msg_type == "cancel_task":
                task_id = str(message.get("task_id") or "")
                self.safety.cancel_task(task_id)
                self._cancel_jobs(task_id)
            elif msg_type == "error" and message.get("error") in {
                "DEVICE_REVOKED_OR_UNKNOWN",
                "AGENT_AUTH_INVALID",
                "AGENT_AUTH_REQUIRED",
            }:
                raise EnrollmentRejectedError("Il Director non riconosce più questo Agent")

    def _cancel_jobs(self, task_id: str | None = None) -> None:
        for current_id, job in list(self.task_jobs.items()):
            if task_id is None or current_id == task_id:
                job.cancel()

    async def run_task(self, message: dict) -> None:
        task_id = message["task_id"]
        capability = message["capability"]
        try:
            self.safety.assert_task_active(task_id)
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
                self.safety.begin_task(task_id)
                self.safety.assert_task_active(task_id)
                result = await self._invoke(handler, args, task_id)
                self.safety.assert_task_active(task_id)
            succeeded = result.get("ok", True) is True and result.get("outcome") != "blocked"
            await self.report(task_id, succeeded, result, None if succeeded else result.get("message", "Lavoro non completato"))
        except asyncio.CancelledError:
            print(f"[kreluna-agent] task {task_id} -> interrotto", flush=True)
        except Exception as exc:
            await self.report(task_id, False, {}, str(exc))
        finally:
            self.safety.finish_task(task_id)

    async def _invoke(self, handler, args: dict, task_id: str):
        extra = {
            "client": httpx.AsyncClient(),
            "director_url": self.director,
            "device_id": self.identity.device_id,
            "task_id": task_id,
            "sign_request": self._sign_request,
            "cancel_check": lambda: self.safety.assert_task_active(task_id),
            "register_process": self.safety.register_process,
        }
        try:
            accepted = set(inspect.signature(handler).parameters)
            call_args = {key: value for key, value in {**args, **extra}.items() if key in accepted}
            if inspect.iscoroutinefunction(handler):
                return await handler(**call_args)
            # I passi che muovono lo schermo possono durare: girano in un thread,
            # così il battito verso il Director non si ferma e il PC non sembra spento.
            self.safety.workers += 1
            def invoke_sync():
                try:
                    return handler(**call_args)
                finally:
                    self.safety.workers -= 1
            outcome = await asyncio.to_thread(invoke_sync)
            if inspect.isawaitable(outcome):
                return await outcome
            return outcome
        finally:
            await extra["client"].aclose()

    def _sign_request(self, path: str, payload: dict) -> dict:
        envelope = {
            **payload,
            "nonce": secrets.token_hex(16),
            "sent_at": int(time.time()),
        }
        return {
            **envelope,
            "signature": b64e(
                sign_bytes(
                    self.identity.private_key,
                    agent_http_payload(path, envelope),
                )
            ),
        }

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
        envelope = {
            "device_id": self.identity.device_id,
            "task_id": task_id,
            "nonce": secrets.token_hex(16),
            "sent_at": int(time.time()),
            "ok": ok,
            "result": clean_result,
            "error": error,
            "evidence": evidence,
        }
        signature = b64e(
            sign_bytes(self.identity.private_key, canonical_json_bytes(envelope))
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.director}/agent/ingest",
                json={**envelope, "signature": signature},
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
