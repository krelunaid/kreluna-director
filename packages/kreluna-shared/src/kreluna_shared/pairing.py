"""Single-paste bootstrap code shared by Director and Agent installers."""

from __future__ import annotations

import json
import re
from typing import TypedDict

from kreluna_shared.crypto import b64d, b64e, canonical_json_bytes

PAIRING_PREFIX = "KRELUNA-COLLEGA-1."
ROLE_PATTERN = re.compile(r"pc-[a-z0-9-]{1,60}")
ENROLLMENT_PATTERN = re.compile(r"KRELUNA-ENROLL-[A-Za-z0-9_-]{35,80}")


class PairingData(TypedDict):
    version: int
    director_url: str
    role: str
    display_name: str
    enrollment_code: str


def create_pairing_code(
    *, director_url: str, role: str, display_name: str, enrollment_code: str
) -> str:
    payload = {
        "v": 1,
        "u": director_url.strip().rstrip("/"),
        "r": role.strip().lower(),
        "n": display_name.strip(),
        "c": enrollment_code.strip(),
    }
    _validate_payload(payload)
    return PAIRING_PREFIX + b64e(canonical_json_bytes(payload)).rstrip("=")


def parse_pairing_code(value: str) -> PairingData:
    code = "".join(value.strip().split())
    if not code.startswith(PAIRING_PREFIX) or len(code) > 1200:
        raise ValueError("Codice di collegamento Kreluna non valido")
    try:
        payload = json.loads(b64d(code.removeprefix(PAIRING_PREFIX)).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Codice di collegamento Kreluna non valido") from exc
    _validate_payload(payload)
    return {
        "version": 1,
        "director_url": payload["u"],
        "role": payload["r"],
        "display_name": payload["n"],
        "enrollment_code": payload["c"],
    }


def _validate_payload(payload: object) -> None:
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("Codice di collegamento Kreluna non valido")
    url = payload.get("u")
    role = payload.get("r")
    name = payload.get("n")
    enrollment = payload.get("c")
    if not isinstance(url, str) or not 10 <= len(url) <= 500:
        raise ValueError("Indirizzo Director mancante nel codice")
    if not isinstance(role, str) or not ROLE_PATTERN.fullmatch(role):
        raise ValueError("Lavoro Agent non valido nel codice")
    if not isinstance(name, str) or not name or len(name) > 120:
        raise ValueError("Nome Agent non valido nel codice")
    if not isinstance(enrollment, str) or not ENROLLMENT_PATTERN.fullmatch(enrollment):
        raise ValueError("Autorizzazione Agent non valida nel codice")
