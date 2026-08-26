from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from kreluna_shared.crypto import b64e, server_public_bytes

from app.config import settings

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=-]+$")


@dataclass(frozen=True)
class RemoteLinkConfig:
    public_url: str
    token: str


def validate_public_url(value: str) -> str:
    url = value.strip().rstrip("/")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError("Indirizzo remoto non valido") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or "." not in host
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or host in {"localhost", "127.0.0.1", "::1"}
        or host.endswith(".local")
    ):
        raise ValueError("Usa l’indirizzo HTTPS pubblico assegnato al Director")
    return url


def validate_tunnel_token(value: str) -> str:
    token = value.strip()
    if not 80 <= len(token) <= 4096 or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Token del collegamento remoto non valido")
    return token


class RemoteTunnelManager:
    """Runs one outbound-only cloudflared connector without exposing its token."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle = None
        self._last_error = ""
        self._connected = False

    @property
    def config_dir(self) -> Path | None:
        configured = settings.director_remote_dir.strip()
        return Path(configured) if configured else None

    @property
    def config_path(self) -> Path | None:
        directory = self.config_dir
        return directory / "remote-link.json" if directory else None

    @property
    def token_path(self) -> Path | None:
        directory = self.config_dir
        return directory / "remote-tunnel.token" if directory else None

    def load(self) -> RemoteLinkConfig | None:
        config_path = self.config_path
        token_path = self.token_path
        if config_path is None or token_path is None:
            return None
        try:
            public_url = self.configured_public_url()
            if not public_url:
                return None
            token = validate_tunnel_token(token_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        return RemoteLinkConfig(public_url=public_url, token=token)

    def configured_public_url(self) -> str:
        config_path = self.config_path
        if config_path is None:
            return ""
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            return validate_public_url(str(payload.get("public_url") or ""))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return ""

    def save(self, public_url: str, token: str) -> RemoteLinkConfig:
        directory = self.config_dir
        if directory is None:
            raise RuntimeError("Questa installazione non supporta ancora il collegamento remoto")
        clean_url = validate_public_url(public_url)
        clean_token = validate_tunnel_token(token)
        directory.mkdir(parents=True, exist_ok=True)
        config_path = directory / "remote-link.json"
        token_path = directory / "remote-tunnel.token"
        config_tmp = directory / "remote-link.json.new"
        token_tmp = directory / "remote-tunnel.token.new"
        config_tmp.write_text(json.dumps({"public_url": clean_url}, indent=2) + "\n", encoding="utf-8")
        token_tmp.write_text(clean_token + "\n", encoding="utf-8")
        for path in (config_tmp, token_tmp):
            with suppress(OSError):
                path.chmod(0o600)
        config_tmp.replace(config_path)
        token_tmp.replace(token_path)
        for path in (config_path, token_path):
            with suppress(OSError):
                path.chmod(0o600)
        settings.director_public_url = clean_url
        return RemoteLinkConfig(public_url=clean_url, token=clean_token)

    def binary(self) -> Path | None:
        configured = settings.director_cloudflared_path.strip()
        if configured:
            path = Path(configured)
            return path if path.is_file() and os.access(path, os.X_OK) else None
        found = shutil.which("cloudflared")
        return Path(found) if found else None

    def public_url(self) -> str:
        return self.configured_public_url()

    def public_hostname(self) -> str:
        return (urlparse(self.public_url()).hostname or "").lower()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._connected = False
            config = self.load()
            binary = self.binary()
            if config is None:
                self._last_error = "Collegamento remoto non configurato"
                return
            if binary is None:
                self._last_error = "Connettore remoto non presente nell’installazione"
                return
            settings.director_public_url = config.public_url
            directory = self.config_dir
            if directory is None:
                self._last_error = "Cartella del collegamento remoto non disponibile"
                return
            try:
                log_path = directory / "remote-tunnel.log"
                self._log_handle = log_path.open("ab")
                child_env = os.environ.copy()
                child_env["TUNNEL_TOKEN"] = config.token
                command = [
                    str(binary),
                    "tunnel",
                    "--no-autoupdate",
                    "--loglevel",
                    "info",
                    "run",
                ]
                if sys.platform == "win32":
                    self._process = subprocess.Popen(
                        command,
                        env=child_env,
                        stdin=subprocess.DEVNULL,
                        stdout=self._log_handle,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    self._process = subprocess.Popen(
                        command,
                        env=child_env,
                        stdin=subprocess.DEVNULL,
                        stdout=self._log_handle,
                        stderr=subprocess.STDOUT,
                    )
                self._last_error = ""
            except OSError:
                self._process = None
                self._last_error = "Il connettore remoto non è riuscito ad avviarsi"
                if self._log_handle is not None:
                    self._log_handle.close()
                    self._log_handle = None

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._connected = False
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> dict:
        config = self.load()
        process_running = self._process is not None and self._process.poll() is None
        if config is None:
            state = "disabled"
            detail = "Configura il collegamento per usare Agent su altri PC."
        elif self.binary() is None:
            state = "connector_missing"
            detail = "Il connettore remoto manca: installa l’aggiornamento completo."
        elif not process_running:
            state = "error"
            detail = self._last_error or "Il collegamento remoto non è avviato."
        elif self._connected:
            state = "connected"
            detail = "Director raggiungibile e collegamento autenticato."
        else:
            state = "starting"
            detail = "Connessione remota in avvio."
        return {
            "configured": config is not None,
            "connector_available": self.binary() is not None,
            "process_running": process_running,
            "connected": bool(process_running and self._connected),
            "state": state,
            "detail": detail,
            "public_url": config.public_url if config else "",
            "token_saved": config is not None,
        }

    async def probe(self) -> dict:
        config = self.load()
        if config is None:
            return self.status()
        if self._process is None or self._process.poll() is not None:
            self.start()
        await asyncio.sleep(0)
        expected_key = b64e(server_public_bytes(settings.director_signing_seed))
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=8) as client:
                response = await client.get(f"{config.public_url}/health")
            payload = response.json() if response.status_code == 200 else {}
            self._connected = bool(
                payload.get("service") == "director-api"
                and payload.get("server_pubkey") == expected_key
            )
            if not self._connected:
                self._last_error = "L’indirizzo remoto non arriva a questo Director"
        except (httpx.HTTPError, ValueError, TypeError):
            self._connected = False
            self._last_error = "Il collegamento remoto non risponde"
        return self.status()


remote_tunnel = RemoteTunnelManager()
