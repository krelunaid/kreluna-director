import hashlib

import pytest
from app.config import Settings
from app.security import hash_password, password_needs_rehash, verify_password
from pydantic import ValidationError


def test_passwords_use_salted_argon2id_hashes():
    first = hash_password("una password lunga")
    second = hash_password("una password lunga")

    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password("una password lunga", first)
    assert not verify_password("password sbagliata", first)
    assert not password_needs_rehash(first)


def test_legacy_password_can_be_verified_only_for_migration():
    legacy_secret = "segreto precedente"
    legacy = hashlib.sha256(f"{legacy_secret}:demo".encode()).hexdigest()

    assert verify_password("demo", legacy, legacy_secret=legacy_secret)
    assert not verify_password("demo", legacy)
    assert password_needs_rehash(legacy)


def test_production_rejects_defaults_and_missing_bootstrap_credentials():
    with pytest.raises(ValidationError, match="Produzione bloccata"):
        Settings(_env_file=None, director_env="production")


def test_desktop_rejects_the_same_shared_defaults_as_production():
    with pytest.raises(ValidationError, match="Produzione bloccata"):
        Settings(_env_file=None, director_env="desktop")


def test_production_accepts_only_explicit_distinct_secrets():
    configured = Settings(
        _env_file=None,
        director_env="production",
        director_signing_seed="signing-7ba425ac87234d3785cd123456789012",
        director_session_secret="session-2b151073caf54ded87ab123456789012",
        director_evidence_key="evidence-79b39b59743046ddac45123456789012",
        director_credential_key="credential-a8b71c2d964f4a72bc45123456789012",
        director_bootstrap_email="titolare@example.test",
        director_bootstrap_password="frase segreta molto lunga",
    )

    assert configured.is_production
