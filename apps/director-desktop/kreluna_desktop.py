#!/usr/bin/env python3
"""Avvio Kreluna come applicazione: API + Agent + finestra."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = Path.home() / "Library" / "Application Support" / "KrelunaDirector"
if sys.platform != "darwin":
    SUPPORT = Path.home() / ".kreluna-director"


def prepare_env() -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    (SUPPORT / "data").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DIRECTOR_DATABASE_URL", f"sqlite+aiosqlite:///{SUPPORT / 'data' / 'kreluna.db'}")
    os.environ.setdefault("DIRECTOR_EVIDENCE_DIR", str(SUPPORT / "data" / "evidence"))
    os.environ.setdefault("KRELUNA_AGENT_DATA_DIR", str(SUPPORT / "data" / "agent"))
    os.environ.setdefault("AGENT_DIRECTOR_URL", "http://127.0.0.1:8080")
    os.environ.setdefault("AGENT_DIRECTOR_WSS", "ws://127.0.0.1:8080/ws/agent")
    os.environ.setdefault("KRELUNA_ENROLLMENT_CODE", "KRELUNA-DEV-ENROLL")
    os.environ.setdefault("KRELUNA_AGENT_ID", "mac-studio")
    os.environ.setdefault("KRELUNA_AGENT_DISPLAY_NAME", "MAC-STUDIO")
    sys.path.insert(0, str(ROOT / "packages" / "kreluna-shared" / "src"))
    sys.path.insert(0, str(ROOT / "apps" / "director-api"))
    sys.path.insert(0, str(ROOT / "apps" / "kreluna-agent"))


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_health(timeout: float = 20) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def notify(text: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", f'display notification "{text}" with title "Kreluna Director"'],
            check=False,
        )


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
    webbrowser.open(url)


def main() -> int:
    prepare_env()
    url = "http://127.0.0.1:8080"
    started_api = False
    agent_proc: subprocess.Popen | None = None
    try:
        if not port_open(8080):
            import uvicorn

            config = uvicorn.Config(
                "app.main:app",
                host="127.0.0.1",
                port=8080,
                log_level="info",
            )
            server = uvicorn.Server(config)
            import threading

            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            started_api = True
        if not wait_health():
            notify("Kreluna non è partita. Controlla Python 3.")
            print("Kreluna: /health non risponde", file=sys.stderr)
            return 1

        env = os.environ.copy()
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
        while True:
            if agent_proc.poll() is not None:
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
        _ = started_api
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
