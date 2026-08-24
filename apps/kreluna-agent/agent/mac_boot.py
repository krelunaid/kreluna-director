"""Avvio Agent su Mac: scegli il ruolo di questo computer, poi collegati al Director."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kreluna_shared.agents import default_agents_path, load_live_agent_roles


def support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "KrelunaAgent"


def config_path() -> Path:
    return support_dir() / "config.json"


def enroll_code_for_role(role: str) -> str:
    return "KRELUNA-" + role.upper().replace("_", "-")


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
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_config(data: dict[str, str]) -> None:
    role = data["role"]
    url = data["director_url"].rstrip("/")
    os.environ["KRELUNA_AGENT_ID"] = role
    os.environ["KRELUNA_AGENT_DISPLAY_NAME"] = data.get("display_name") or role.upper()
    os.environ["KRELUNA_ENROLLMENT_CODE"] = enroll_code_for_role(role)
    os.environ["AGENT_DIRECTOR_URL"] = url
    os.environ["AGENT_DIRECTOR_WSS"] = url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/agent"
    # Ogni lavoro ha la sua cartella: cambiando lavoro l'Agent si presenta come
    # quel PC, invece di riusare l'identità del ruolo di prima.
    base = Path(os.environ.get("KRELUNA_AGENT_DATA_DIR") or (support_dir() / "data"))
    if base.name != role:
        base = base / role
    os.environ["KRELUNA_AGENT_DATA_DIR"] = str(base)


def ask_osascript() -> dict[str, str] | None:
    roles = load_live_agent_roles(roles_yaml())
    labels = [f"{role.display_name} — {role.job}" for role in roles]
    listed = ", ".join(f'"{item}"' for item in labels)
    script = f'''
set picked to choose from list {{{listed}}} with prompt "Questo Mac quale lavoro fa? Un Agent, un ruolo." OK button name "Avanti" cancel button name "Annulla"
if picked is false then return "CANCEL"
return item 1 of picked
'''
    choose = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    label = choose.stdout.strip()
    if choose.returncode != 0 or label in {"", "CANCEL"}:
        return None
    found = next((item for item in roles if f"{item.display_name} — {item.job}" == label), None)
    if found is None:
        return None
    url_script = f'''
set answer to display dialog "Indirizzo del Director (cervello)" default answer "{default_director_url()}" buttons {{"Annulla", "Avvia"}} default button "Avvia"
if button returned of answer is "Annulla" then return "CANCEL"
return text returned of answer
'''
    typed = subprocess.run(["osascript", "-e", url_script], capture_output=True, text=True, check=False)
    url = typed.stdout.strip()
    if typed.returncode != 0 or url in {"", "CANCEL"}:
        return None
    return {"role": found.role, "display_name": found.display_name, "director_url": url}


def confirm_existing(data: dict[str, str]) -> dict[str, str] | None:
    if sys.platform != "darwin":
        return data
    name = data.get("display_name") or data.get("role") or "questo Mac"
    script = f'''
set picked to display dialog "Questo Mac è {name}. Scegli il lavoro di questo computer (fatture, F24, visure…)." buttons {{"Cambia lavoro", "Avvia"}} default button "Avvia" with title "Kreluna Agent"
if button returned of picked is "Cambia lavoro" then return "CHANGE"
return "KEEP"
'''
    choice = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if choice.returncode != 0:
        return None
    if choice.stdout.strip() != "CHANGE":
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
