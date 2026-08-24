from __future__ import annotations

from kreluna_shared.crypto import server_public_bytes
from kreluna_shared.update import (
    APP_VERSION,
    evaluate_update,
    is_newer,
    manifest_payload,
    runtime_needs_refresh,
    sign_manifest,
    verify_manifest,
    write_installed_version,
)

SEED = "kreluna-dev-signing-seed-change-in-production"


def test_is_newer():
    assert is_newer("0.4.1", "0.4.0") is True
    assert is_newer("0.4.0", "0.4.0") is False
    assert is_newer("0.3.9", "0.4.0") is False


def test_sign_and_verify_manifest():
    payload = manifest_payload()
    signature = sign_manifest(SEED, payload)
    public = server_public_bytes(SEED)
    assert verify_manifest(public, payload, signature) is True
    assert verify_manifest(SEED, payload, signature) is True
    tampered = dict(payload)
    tampered["version"] = "9.9.9"
    assert verify_manifest(public, tampered, signature) is False
    assert verify_manifest(public, payload, "AAAA") is False


def test_evaluate_update_same_version():
    assert evaluate_update({"version": APP_VERSION}) is None
    message = evaluate_update({"version": "9.0.0", "notes": "test"})
    assert message is not None
    assert "9.0.0" in message
    assert "reinstalla" in message.lower()


def test_runtime_stamp(tmp_path):
    assert runtime_needs_refresh(tmp_path) is True
    write_installed_version(tmp_path, APP_VERSION)
    assert runtime_needs_refresh(tmp_path) is False
    write_installed_version(tmp_path, "0.0.1")
    assert runtime_needs_refresh(tmp_path) is True
