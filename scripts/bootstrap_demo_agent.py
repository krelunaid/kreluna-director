from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx


def local_device_id(state_path: Path) -> str:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(payload.get("device_id") or "")


def main() -> int:
    director = os.getenv("AGENT_DIRECTOR_URL", "http://127.0.0.1:8080").rstrip("/")
    agent_id = os.getenv("KRELUNA_AGENT_ID", "pc-fatture")
    data_dir = Path(os.getenv("KRELUNA_AGENT_DATA_DIR", "data/agent"))
    known_device = local_device_id(data_dir / "state.json")

    with httpx.Client(base_url=director, timeout=10) as client:
        login = client.post(
            "/auth/login",
            json={
                "email": os.getenv("KRELUNA_DEMO_EMAIL", "andrea@studio.demo"),
                "password": os.getenv("KRELUNA_DEMO_PASSWORD", "demo"),
                "remember_device": False,
            },
        )
        login.raise_for_status()
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        agents = client.get("/agents", headers=headers)
        agents.raise_for_status()
        target = next(
            (item for item in agents.json()["agents"] if item["agent_id"] == agent_id),
            None,
        )
        if target is None:
            raise RuntimeError(f"Ruolo Agent demo non trovato: {agent_id}")
        if known_device and target.get("device_id") == known_device:
            print("[demo] Agent locale già iscritto", file=sys.stderr)
            return 0
        if target.get("presence") != "waiting_install":
            raise RuntimeError(
                "Il ruolo demo risulta installato su un altro Agent. "
                "Revocalo dalla dashboard prima di collegare questo computer."
            )
        issued = client.post(f"/agents/{agent_id}/enrollment", headers=headers)
        issued.raise_for_status()
        print("[demo] Codice monouso creato per l'Agent locale", file=sys.stderr)
        print(issued.json()["enrollment_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
