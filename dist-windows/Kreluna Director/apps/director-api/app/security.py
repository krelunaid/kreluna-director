from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from kreluna_shared.crypto import b64d, b64e


def hash_password(secret: str, password: str) -> str:
    return hashlib.sha256(f"{secret}:{password}".encode()).hexdigest()


def verify_password(secret: str, password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(secret, password), hashed)


def issue_session(secret: str, claims: dict[str, Any], ttl: int = 60 * 60 * 12) -> str:
    body = {**claims, "exp": int(time.time()) + ttl}
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return b64e(payload) + "." + b64e(sig)


def read_session(secret: str, token: str) -> dict[str, Any]:
    try:
        raw_payload, raw_sig = token.split(".", 1)
    except ValueError as exc:
        raise PermissionError("SESSION_MALFORMED") from exc
    payload = b64d(raw_payload)
    sig = b64d(raw_sig)
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise PermissionError("SESSION_INVALID")
    body = json.loads(payload)
    if int(body.get("exp", 0)) < int(time.time()):
        raise PermissionError("SESSION_EXPIRED")
    return body
