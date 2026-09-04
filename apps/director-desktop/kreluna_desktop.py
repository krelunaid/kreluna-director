#!/usr/bin/env python3
"""Avvio Kreluna Director come applicazione autonoma: API + finestra."""

from __future__ import annotations

import json
import os
import plistlib
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

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


def _local_secret(name: str) -> str:
    """Create a per-installation secret outside the signed application bundle."""

    path = SUPPORT / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""
    if len(value) < 32:
        value = secrets.token_urlsafe(48)
        path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def _managed_ai_token() -> str:
    """Load the revocable Kreluna license; never bundle the upstream xAI key."""

    path = SUPPORT / "managed_ai.token"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if not value.startswith("kreluna_live_") or not 50 <= len(value) <= 100:
        return ""
    return value


def _initial_owner() -> dict[str, str]:
    """Create one strong local owner account instead of shipping demo credentials."""

    path = SUPPORT / "owner-access.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    email = str(data.get("email") or "titolare@kreluna.local").strip().lower()
    password = str(data.get("password") or "")
    if len(password) < 20:
        password = secrets.token_urlsafe(24)
        path.write_text(
            json.dumps({"email": email, "password": password}, indent=2) + "\n",
            encoding="utf-8",
        )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"email": email, "password": password}


def agent_support_dir() -> Path:
    configured = os.environ.get("KRELUNA_AGENT_SUPPORT_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / "Library" / "Application Support" / "KrelunaAgent"


def installed_mac_agent_app() -> Path:
    configured = os.environ.get("KRELUNA_INSTALLED_AGENT_APP", "").strip()
    return Path(configured) if configured else Path("/Applications/Kreluna Agent.app")


def start_installed_mac_agent() -> subprocess.Popen | None:
    """Avvia soltanto l'Agent Mac installato e firmato, con una configurazione locale valida."""

    if sys.platform != "darwin" or os.environ.get("KRELUNA_START_INSTALLED_AGENT", "1") == "0":
        return None
    app = installed_mac_agent_app()
    info_path = app / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as fh:
            info = plistlib.load(fh)
    except (FileNotFoundError, OSError, plistlib.InvalidFileException):
        return None
    if info.get("CFBundleIdentifier") != "studio.kreluna.agent":
        return None
    executable_name = str(info.get("CFBundleExecutable") or "")
    if executable_name != "Kreluna":
        return None
    executable = app / "Contents" / "MacOS" / executable_name
    if not executable.is_file():
        return None
    verified = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        capture_output=True,
        check=False,
    )
    if verified.returncode != 0:
        return None
    running = subprocess.run(
        ["/usr/bin/pgrep", "-f", str(executable)],
        capture_output=True,
        check=False,
    )
    if running.returncode == 0:
        return None
    config_path = agent_support_dir() / "config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    role = str(data.get("role") or "").strip().lower()
    director_url = str(data.get("director_url") or "").strip().rstrip("/")
    if not role.startswith("pc-") or not 3 <= len(role) <= 80:
        return None
    parsed = urlparse(director_url)
    remote_https = parsed.scheme == "https" and bool(parsed.hostname)
    local_http = (
        parsed.scheme == "http"
        and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        and parsed.port == 8080
    )
    if (
        not (remote_https or local_http)
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    env = os.environ.copy()
    env["KRELUNA_SKIP_SETUP"] = "1"
    env["KRELUNA_AGENT_ID"] = role
    env["KRELUNA_AGENT_DISPLAY_NAME"] = str(data.get("display_name") or role.upper())
    env["AGENT_DIRECTOR_URL"] = director_url
    env["AGENT_DIRECTOR_WSS"] = (
        director_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/agent"
    )
    target = str(data.get("fatture_target") or "").strip()
    if target:
        env["KRELUNA_FATTURE_TARGET"] = target
    return subprocess.Popen([str(executable)], env=env)


def prepare_env() -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    (SUPPORT / "data").mkdir(parents=True, exist_ok=True)
    owner = _initial_owner()
    os.environ.setdefault("DIRECTOR_ENV", "desktop")
    os.environ.setdefault("DIRECTOR_DATABASE_URL", f"sqlite+aiosqlite:///{SUPPORT / 'data' / 'kreluna.db'}")
    os.environ.setdefault("DIRECTOR_EVIDENCE_DIR", str(SUPPORT / "data" / "evidence"))
    os.environ.setdefault("DIRECTOR_SIGNING_SEED", _local_secret("signing.seed"))
    os.environ.setdefault("DIRECTOR_SESSION_SECRET", _local_secret("session.key"))
    os.environ.setdefault("DIRECTOR_EVIDENCE_KEY", _local_secret("evidence.key"))
    os.environ.setdefault("DIRECTOR_CREDENTIAL_KEY", _local_secret("credential.key"))
    os.environ.setdefault("KRELUNA_SUPPORT_DIR", str(SUPPORT))
    os.environ.setdefault("KRELUNA_APP_ROOT", str(ROOT))
    gmail_client = SUPPORT / "gmail-oauth-client.json"
    if gmail_client.is_file():
        os.environ.setdefault("GMAIL_OAUTH_CLIENT_FILE", str(gmail_client))
    remote_dir = SUPPORT / "remote"
    os.environ.setdefault("DIRECTOR_REMOTE_DIR", str(remote_dir))
    remote_config = remote_dir / "remote-link.json"
    try:
        remote_data = json.loads(remote_config.read_text(encoding="utf-8"))
        remote_url = str(remote_data.get("public_url") or "").strip().rstrip("/")
        parsed_remote = urlparse(remote_url)
        if (
            parsed_remote.scheme == "https"
            and parsed_remote.hostname
            and not parsed_remote.username
            and not parsed_remote.password
            and parsed_remote.path in {"", "/"}
            and not parsed_remote.query
            and not parsed_remote.fragment
        ):
            os.environ.setdefault("DIRECTOR_PUBLIC_URL", remote_url)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    os.environ.setdefault("DIRECTOR_BOOTSTRAP_EMAIL", owner["email"])
    os.environ.setdefault("DIRECTOR_BOOTSTRAP_PASSWORD", owner["password"])
    os.environ.setdefault("DIRECTOR_BOOTSTRAP_NAME", "Andrea Gadducci")
    managed_token = _managed_ai_token()
    if managed_token:
        os.environ.setdefault("KRELUNA_MANAGED_AI_TOKEN", managed_token)
    os.environ.setdefault("KRELUNA_DIRECTOR_URL", API_URL)
    sys.path.insert(0, str(ROOT / "packages" / "kreluna-shared" / "src"))
    sys.path.insert(0, str(ROOT / "apps" / "director-api"))


def show_initial_access_once() -> None:
    stamp = SUPPORT / "owner-access-shown"
    if stamp.exists():
        return
    owner = _initial_owner()
    text = (
        "Credenziali iniziali Kreluna\n\n"
        f"Email: {owner['email']}\nPassword: {owner['password']}\n\n"
        "Conservale in un posto sicuro. Non sono credenziali demo."
    )
    if sys.platform == "darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                'on run argv\ndisplay dialog (item 1 of argv) buttons {"Ho salvato"} default button "Ho salvato" with title "Kreluna Director"\nend run',
                text,
            ],
            check=False,
        )
    elif sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Kreluna Director", 0x40)
        except Exception:
            return
    else:
        return
    stamp.write_text("shown\n", encoding="utf-8")
    try:
        stamp.chmod(0o600)
    except OSError:
        pass


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_health(timeout: float = 120) -> bool:
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
        script = (
            "on run argv\n"
            'display notification (item 1 of argv) with title "Kreluna Director"\n'
            "end run"
        )
        subprocess.run(
            ["osascript", "-e", script, text],
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
    packaged = os.environ.get("KRELUNA_DESKTOP_APP", "") == "1"
    if packaged and sys.platform in {"darwin", "win32"}:
        from native_window import run_native_window

        run_native_window(url, storage_path=SUPPORT / "webview")
        return
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


def _update_notification_due(version: str, *, now: float | None = None) -> bool:
    stamp = SUPPORT / "last_update_notification.json"
    current = now if now is not None else time.time()
    try:
        previous = json.loads(stamp.read_text(encoding="utf-8"))
        if previous.get("version") == version and current - float(previous.get("at") or 0) < 86400:
            return False
    except Exception:
        pass
    stamp.write_text(json.dumps({"version": version, "at": current}), encoding="utf-8")
    return True


def check_updates() -> None:
    from kreluna_shared.update import APP_VERSION

    try:
        with urllib.request.urlopen(f"{API_URL}/update/status", timeout=10) as response:
            status = json.loads(response.read().decode())
    except Exception as exc:
        _write_log(f"Canale aggiornamenti non raggiungibile: {exc}")
        return

    latest = str(status.get("latest_version") or "")
    if status.get("available") is True and latest and _update_notification_due(latest):
        notify(
            f"È disponibile Kreluna Director {latest}. Apri Kreluna per aggiornare.",
            dialog=True,
        )
        _write_log(f"Aggiornamento segnalato: {latest}")
        return
    if status.get("state") == "unavailable":
        _write_log("Canale aggiornamenti temporaneamente non raggiungibile.")
        return
    _write_log(f"Versione attuale {APP_VERSION}: nessun aggiornamento.")


def main() -> int:
    prepare_env()
    url = API_URL
    agent_proc: subprocess.Popen | None = None
    server = None
    server_thread = None
    try:
        if port_open(8080):
            health = health_info()
            if health is None or health.get("service") != "director-api":
                notify("La porta 8080 è già usata da un altro programma. Chiudilo e riapri Kreluna.", dialog=True)
                return 1
            if os.environ.get("KRELUNA_DESKTOP_APP", "") == "1" and sys.platform == "darwin":
                from native_window import activate_existing_mac_window

                if activate_existing_mac_window(url):
                    notify("Kreluna Director è già aperto.")
                    return 0
            notify("Kreluna Director è già aperto.")
            try:
                open_window(url)
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                _write_log(f"Finestra Kreluna non disponibile: {exc}")
                notify(str(exc), dialog=True)
                return 1
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
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
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
        elif os.environ.get("KRELUNA_DESKTOP_APP", "") == "1" and sys.platform == "darwin":
            agent_proc = start_installed_mac_agent()
        show_initial_access_once()
        notify("Kreluna è aperta. Usa le credenziali personali della tua installazione.")
        print("Kreluna Director:", url)
        check_updates()
        try:
            open_window(url)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            _write_log(f"Finestra Kreluna non disponibile: {exc}")
            notify(str(exc), dialog=True)
            return 1
        if os.environ.get("KRELUNA_DESKTOP_APP", "") == "1" and sys.platform in {
            "darwin",
            "win32",
        }:
            return 0
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
        if server is not None:
            server.should_exit = True
        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
