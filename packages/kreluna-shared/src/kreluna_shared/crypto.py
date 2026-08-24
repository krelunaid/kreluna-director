from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kreluna_shared.protocol import SignedGrant


def generate_device_keypair() -> tuple[bytes, bytes]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, public


def sign_bytes(private_key: bytes, payload: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    return key.sign(payload)


def verify_bytes(public_key: bytes, payload: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        return True
    except Exception:
        return False


def fingerprint_device(hostname: str, agent_id: str, extra: str = "") -> str:
    material = f"{hostname}|{agent_id}|{extra}".encode()
    return hashlib.sha256(material).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def derive_aes_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_bytes(secret: str, plaintext: bytes) -> bytes:
    key = derive_aes_key(secret)
    nonce = os.urandom(12)
    cipher = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + cipher


def decrypt_bytes(secret: str, blob: bytes) -> bytes:
    key = derive_aes_key(secret)
    nonce, cipher = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, cipher, None)


def server_private_from_seed(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode("utf-8")).digest())


def server_public_bytes(seed: str) -> bytes:
    return server_private_from_seed(seed).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def sign_grant(secret: str, grant: SignedGrant) -> str:
    body = grant.model_dump(mode="json")
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    sig = server_private_from_seed(secret).sign(payload)
    return b64e(payload) + "." + b64e(sig)


def verify_grant(
    public_or_secret: str | bytes,
    token: str,
    *,
    expected_task: UUID,
    expected_device: UUID,
    expected_capability: str,
    consumed_nonces: set[str],
    now: int | None = None,
) -> SignedGrant:
    try:
        raw_payload, raw_sig = token.split(".", 1)
    except ValueError as exc:
        raise PermissionError("GRANT_MALFORMED") from exc
    payload = b64d(raw_payload)
    sig = b64d(raw_sig)
    public = (
        public_or_secret
        if isinstance(public_or_secret, bytes)
        else server_public_bytes(public_or_secret)
    )
    if not verify_bytes(public, payload, sig):
        raise PermissionError("GRANT_INVALID")
    grant = SignedGrant.model_validate(json.loads(payload))
    if grant.task_id != expected_task:
        raise PermissionError("GRANT_TASK_MISMATCH")
    if grant.device_id != expected_device:
        raise PermissionError("GRANT_DEVICE_MISMATCH")
    if grant.capability != expected_capability:
        raise PermissionError("GRANT_CAPABILITY_MISMATCH")
    if grant.nonce in consumed_nonces:
        raise PermissionError("GRANT_REPLAY")
    if grant.exp < (now if now is not None else int(time.time())):
        raise PermissionError("GRANT_EXPIRED")
    return grant


def redact_text(value: str) -> str:
    import re

    patterns = [
        (r"(?i)(password|passwd|pwd|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]"),
        (r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[IBAN_REDACTED]"),
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]+\b", "[JWT_REDACTED]"),
    ]
    redacted = value
    for pattern, repl in patterns:
        redacted = re.sub(pattern, repl, redacted)
    return redacted
