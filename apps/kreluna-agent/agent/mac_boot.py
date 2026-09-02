"""Avvio Agent su Mac: scegli il ruolo di questo computer, poi collegati al Director."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from kreluna_shared.agents import default_agents_path, load_live_agent_roles
from kreluna_shared.pairing import parse_pairing_code


def support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "KrelunaAgent"


def config_path() -> Path:
    return support_dir() / "config.json"


def enrollment_path() -> Path:
    return support_dir() / "enrollment.once"


def validated_enrollment_code(value: str) -> str:
    code = value.strip()
    if not code.startswith("KRELUNA-ENROLL-") or not 50 <= len(code) <= 100:
        raise ValueError("Usa il codice monouso generato dal Director")
    return code


def roles_yaml() -> Path:
    bundled = Path(__file__).resolve().parents[3] / "policies" / "agents.yaml"
    return bundled if bundled.exists() else default_agents_path()


def default_director_url() -> str:
    for candidate in (
        Path(__file__).resolve().parents[3] / "director.url",
        Path(__file__).resolve().parents[2] / "director.url",
    ):
        if candidate.exists():
            line = candidate.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if line:
                return line
    return os.environ.get("AGENT_DIRECTOR_URL", "http://127.0.0.1:8080")


def validated_director_url(value: str) -> str:
    url = value.strip().rstrip("/")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError("Indirizzo Director non valido") from exc
    host = (parsed.hostname or "").lower()
    local = host in {"127.0.0.1", "localhost", "::1"}
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Indirizzo Director non valido")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("Fuori da questo Mac il Director deve usare un indirizzo HTTPS")
    if not host:
        raise ValueError("Indirizzo Director non valido")
    return url


def validated_invoice_target(value: str) -> str:
    """Accetta un portale HTTPS o un'app locale esplicita, mai un comando."""

    target = value.strip()
    if not target:
        return ""
    try:
        parsed = urlparse(target)
    except ValueError as exc:
        raise ValueError("Percorso fatture non valido") from exc
    if parsed.scheme:
        host = (parsed.hostname or "").lower()
        local = host in {"127.0.0.1", "localhost", "::1"}
        if parsed.username or parsed.password or not host:
            raise ValueError("Indirizzo fatture non valido")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("Il portale fatture deve usare HTTPS")
        return target
    path = Path(target).expanduser()
    if not path.is_absolute() or not path.exists():
        raise ValueError("Il programma fatture non esiste in quel percorso")
    if sys.platform == "darwin" and path.suffix.lower() != ".app":
        raise ValueError("Sul Mac scegli un programma con estensione .app")
    if sys.platform == "win32" and path.suffix.lower() != ".exe":
        raise ValueError("Su Windows scegli un programma con estensione .exe")
    return str(path.resolve())


def load_config() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, str]) -> None:
    support_dir().mkdir(parents=True, exist_ok=True)
    code = data.pop("enrollment_code", "").strip()
    if code:
        try:
            validated_enrollment_code(code)
        except ValueError:
            enrollment_path().unlink(missing_ok=True)
        else:
            enrollment_path().write_text(code + "\n", encoding="utf-8")
            try:
                enrollment_path().chmod(0o600)
            except OSError:
                pass
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        config_path().chmod(0o600)
    except OSError:
        pass


def apply_config(data: dict[str, str]) -> None:
    role = data["role"]
    url = validated_director_url(data["director_url"])
    os.environ["KRELUNA_AGENT_ID"] = role
    os.environ["KRELUNA_AGENT_DISPLAY_NAME"] = data.get("display_name") or role.upper()
    enrollment_code = data.get("enrollment_code", "").strip()
    if not enrollment_code:
        try:
            enrollment_code = enrollment_path().read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            enrollment_code = ""
    if enrollment_code:
        os.environ["KRELUNA_ENROLLMENT_CODE"] = validated_enrollment_code(enrollment_code)
        os.environ["KRELUNA_ENROLLMENT_CODE_FILE"] = str(enrollment_path())
    else:
        os.environ.pop("KRELUNA_ENROLLMENT_CODE", None)
        os.environ.pop("KRELUNA_ENROLLMENT_CODE_FILE", None)
    os.environ["AGENT_DIRECTOR_URL"] = url
    os.environ["AGENT_DIRECTOR_WSS"] = url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/agent"
    target = data.get("fatture_target", "").strip()
    if target:
        os.environ["KRELUNA_FATTURE_TARGET"] = validated_invoice_target(target)
    else:
        os.environ.pop("KRELUNA_FATTURE_TARGET", None)
    # Ogni lavoro ha la sua cartella: cambiando lavoro l'Agent si presenta come
    # quel PC, invece di riusare l'identità del ruolo di prima.
    base = Path(os.environ.get("KRELUNA_AGENT_DATA_DIR") or (support_dir() / "data"))
    if base.name != role:
        base = base / role
    os.environ["KRELUNA_AGENT_DATA_DIR"] = str(base)


def ask_osascript() -> dict[str, str] | None:
    roles = load_live_agent_roles(roles_yaml())
    code_script = '''
set answer to display dialog "Incolla il Codice di collegamento copiato dal Director" default answer "" buttons {"Annulla", "Collega"} default button "Collega" with title "Kreluna Agent"
if button returned of answer is "Annulla" then return "CANCEL"
return text returned of answer
'''
    code_answer = subprocess.run(
        ["osascript", "-e", code_script], capture_output=True, text=True, check=False
    )
    pasted = code_answer.stdout.strip()
    if code_answer.returncode != 0 or pasted == "CANCEL":
        return None
    try:
        linked = parse_pairing_code(pasted)
        url = validated_director_url(linked["director_url"])
        code = validated_enrollment_code(linked["enrollment_code"])
    except ValueError as exc:
        message = _escape_applescript(str(exc))
        subprocess.run(
            ["osascript", "-e", f'display dialog "{message}" buttons {{"OK"}} default button "OK"'],
            capture_output=True,
            text=True,
            check=False,
        )
        return None
    found = next((item for item in roles if item.role == linked["role"]), None)
    if found is None:
        return None
    data = {
        "role": found.role,
        "display_name": found.display_name,
        "director_url": url,
        "enrollment_code": code,
    }
    if found.role == "pc-fatture":
        target = ask_invoice_target("")
        if target is not None:
            data["fatture_target"] = target
    return data


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def ask_invoice_target(current: str) -> str | None:
    """Chiede il percorso senza inserirlo nel codice o accettare comandi."""

    if sys.platform != "darwin":
        return current
    default = _escape_applescript(current)
    script = f'''
set answer to display dialog "Percorso del programma fatture (.app) oppure indirizzo HTTPS del portale. Puoi lasciarlo vuoto e usare la prova locale." default answer "{default}" buttons {{"Annulla", "Salva"}} default button "Salva" with title "PC-FATTURE"
if button returned of answer is "Annulla" then return "CANCEL"
return text returned of answer
'''
    typed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    value = typed.stdout.strip()
    if typed.returncode != 0 or value == "CANCEL":
        return None
    try:
        return validated_invoice_target(value)
    except ValueError as exc:
        message = _escape_applescript(str(exc))
        subprocess.run(
            ["osascript", "-e", f'display dialog "{message}" buttons {{"OK"}} default button "OK"'],
            capture_output=True,
            text=True,
            check=False,
        )
        return None


def confirm_existing(data: dict[str, str]) -> dict[str, str] | None:
    if sys.platform != "darwin":
        return data
    name = data.get("display_name") or data.get("role") or "questo Mac"
    if data.get("role") == "pc-fatture":
        script = f'''
set picked to display dialog "Questo Mac è {name}. Puoi avviarlo oppure impostare il percorso del programma fatture." buttons {{"Cambia lavoro", "Percorso fatture", "Avvia"}} default button "Avvia" with title "Kreluna Agent"
if button returned of picked is "Cambia lavoro" then return "CHANGE"
if button returned of picked is "Percorso fatture" then return "PATH"
return "KEEP"
'''
    else:
        script = f'''
set picked to display dialog "Questo Mac è {name}. Scegli il lavoro di questo computer (fatture, F24, visure…)." buttons {{"Cambia lavoro", "Avvia"}} default button "Avvia" with title "Kreluna Agent"
if button returned of picked is "Cambia lavoro" then return "CHANGE"
return "KEEP"
'''
    choice = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if choice.returncode != 0:
        return None
    selected = choice.stdout.strip()
    if selected == "PATH":
        target = ask_invoice_target(data.get("fatture_target", ""))
        if target is not None:
            return {**data, "fatture_target": target}
        return data
    if selected != "CHANGE":
        return data
    return ask_osascript() or data


def ask_config() -> dict[str, str] | None:
    if sys.platform == "darwin":
        picked = ask_osascript()
        if picked:
            return picked
    return None


def main() -> int:
    data = load_config()
    preset_role = os.environ.get("KRELUNA_AGENT_ID")
    preset_url = os.environ.get("AGENT_DIRECTOR_URL")
    if preset_role and preset_url and os.environ.get("KRELUNA_SKIP_SETUP") == "1":
        data = {
            "role": preset_role,
            "display_name": os.environ.get("KRELUNA_AGENT_DISPLAY_NAME", ""),
            "director_url": preset_url,
            "enrollment_code": os.environ.get("KRELUNA_ENROLLMENT_CODE", ""),
            "fatture_target": os.environ.get("KRELUNA_FATTURE_TARGET", ""),
        }
    elif not data.get("role") or not data.get("director_url"):
        asked = ask_config()
        if not asked or not asked.get("director_url"):
            print("Serve scegliere il ruolo di questo Mac e l'indirizzo del Director.", file=sys.stderr)
            return 1
        save_config(asked)
        data = asked
    else:
        data = confirm_existing(data)
        if not data:
            print("Avvio annullato.", file=sys.stderr)
            return 1
        save_config(data)
    apply_config(data)
    import asyncio

    from agent.main import AgentApp

    asyncio.run(AgentApp().start())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
