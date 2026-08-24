from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from kreluna_shared.crypto import b64d, b64e

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    """Crea un hash Argon2id lento e salato con parametri espliciti."""

    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, hashed: str, *, legacy_secret: str = "") -> bool:
    """Verifica Argon2id e permette la migrazione dagli hash SHA-256 esistenti."""

    if hashed.startswith("$argon2id$"):
        try:
            return PASSWORD_HASHER.verify(hashed, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False
    if not legacy_secret or len(hashed) != 64:
        return False
    legacy = hashlib.sha256(f"{legacy_secret}:{password}".encode()).hexdigest()
    return hmac.compare_digest(legacy, hashed)


def password_needs_rehash(hashed: str) -> bool:
    if not hashed.startswith("$argon2id$"):
        return True
    try:
        return PASSWORD_HASHER.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


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
