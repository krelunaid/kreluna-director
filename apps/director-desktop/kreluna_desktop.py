#!/usr/bin/env python3
"""Avvio Kreluna Director come applicazione autonoma: API + finestra."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KrelunaDirector"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "KrelunaDirector"
    return Path.home() / ".kreluna-director"


SUPPORT = support_dir()
API_URL = (
    os.environ.get("KRELUNA_DIRECTOR_URL")
    or os.environ.get("AGENT_DIRECTOR_URL")
    or "http://127.0.0.1:8080"
).rstrip("/")


def prepare_env() -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    (SUPPORT / "data").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DIRECTOR_DATABASE_URL", f"sqlite+aiosqlite:///{SUPPORT / 'data' / 'kreluna.db'}")
    os.environ.setdefault("DIRECTOR_EVIDENCE_DIR", str(SUPPORT / "data" / "evidence"))
    os.environ.setdefault("KRELUNA_DIRECTOR_URL", API_URL)
    sys.path.insert(0, str(ROOT / "packages" / "kreluna-shared" / "src"))
    sys.path.insert(0, str(ROOT / "apps" / "director-api"))


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_health(timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API_URL}/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def health_info() -> dict | None:
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=1) as response:
            payload = json.loads(response.read().decode())
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def notify(text: str, *, dialog: bool = False) -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", f'display notification "{text}" with title "Kreluna Director"'],
            check=False,
        )
        return
    if sys.platform == "win32" and dialog:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Kreluna Director", 0x40)
            return
        except Exception:
            pass
    print(text)


def open_window(url: str) -> None:
    if sys.platform == "darwin":
        chrome = Path("/Applications/Google Chrome.app")
        if chrome.exists():
            subprocess.Popen(
                ["open", "-na", "Google Chrome", "--args", f"--app={url}"],
            )
            return
        subprocess.Popen(["open", url])
        return
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or "")
        program_files = Path(os.environ.get("PROGRAMFILES") or "")
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)") or "")
        candidates = [
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            local / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        browser = next((path for path in candidates if path.is_file()), None)
        if browser is not None:
            subprocess.Popen([str(browser), f"--app={url}", "--start-maximized"])
            return
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    webbrowser.open(url)


def _write_log(text: str) -> None:
    from datetime import datetime

    line = f"{datetime.now().isoformat(timespec='seconds')}  {text}\n"
    with (SUPPORT / "kreluna.log").open("a", encoding="utf-8") as fh:
        fh.write(line)


def check_updates() -> None:
    from kreluna_shared.crypto import b64d
    from kreluna_shared.update import APP_VERSION, evaluate_update, verify_manifest

    update_url = os.environ.get("KRELUNA_UPDATE_URL", f"{API_URL}/update/manifest")
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=8) as response:
            health = json.loads(response.read().decode())
        with urllib.request.urlopen(update_url, timeout=8) as response:
            data = json.loads(response.read().decode())
    except Exception as exc:
        _write_log(f"Canale aggiornamenti non raggiungibile: {exc}")
        return

    payload = data.get("manifest") if isinstance(data.get("manifest"), dict) else data
    signature = str(data.get("signature") or "")
    pubkey_b64 = os.environ.get("KRELUNA_UPDATE_PUBKEY") or str(health.get("server_pubkey") or "")
    try:
        public = b64d(pubkey_b64) if pubkey_b64 else b""
    except Exception:
        public = b""
    if not public or not signature or not verify_manifest(public, payload, signature):
        _write_log("Manifest aggiornamenti non valido: ignorato.")
        return

    message = evaluate_update(payload, APP_VERSION)
    if message:
        notify(message, dialog=True)
        _write_log(f"Aggiornamento segnalato: {payload.get('version')}")
        return
    _write_log(f"Versione attuale {APP_VERSION}: nessun aggiornamento.")


def main() -> int:
    prepare_env()
    url = API_URL
    agent_proc: subprocess.Popen | None = None
    try:
        if port_open(8080):
            health = health_info()
            if health is None or health.get("service") != "director-api":
                notify("La porta 8080 è già usata da un altro programma. Chiudilo e riapri Kreluna.", dialog=True)
                return 1
            open_window(url)
            notify("Kreluna Director è già aperto.")
            return 0
        else:
            import threading

            import uvicorn

            config = uvicorn.Config(
                "app.main:app",
                host="127.0.0.1",
                port=8080,
                log_level="info",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
        if not wait_health():
            notify("Kreluna non è partita. Reinstalla lo zip nuovo.", dialog=True)
            print("Kreluna: /health non risponde", file=sys.stderr)
            return 1

        start_local_agent = os.environ.get("KRELUNA_START_LOCAL_AGENT", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        env = os.environ.copy()
        if start_local_agent and (ROOT / "apps" / "kreluna-agent").is_dir():
            env["PYTHONPATH"] = os.pathsep.join(
                [
                    str(ROOT / "packages" / "kreluna-shared" / "src"),
                    str(ROOT / "apps" / "kreluna-agent"),
                    str(ROOT / "apps" / "director-api"),
                    env.get("PYTHONPATH", ""),
                ]
            )
            agent_proc = subprocess.Popen(
                [sys.executable, "-m", "agent.main"],
                cwd=str(ROOT),
                env=env,
            )
        open_window(url)
        notify("Kreluna è aperta. Entra con andrea@studio.demo / demo")
        print("Kreluna Director:", url)
        print("Login: andrea@studio.demo / demo")
        check_updates()
        while True:
            if agent_proc is not None and agent_proc.poll() is not None:
                agent_proc = subprocess.Popen(
                    [sys.executable, "-m", "agent.main"],
                    cwd=str(ROOT),
                    env=env,
                )
            time.sleep(2)
    except KeyboardInterrupt:
        return 0
    finally:
        if agent_proc and agent_proc.poll() is None:
            agent_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
