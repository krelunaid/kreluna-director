from types import SimpleNamespace

import pytest
from app.services.gmail import configuration_status


@pytest.mark.parametrize("redirect,expected", [
    ("", False),
    ("http://external.example/callback", False),
    ("https://example.org/callback", True),
    ("http://127.0.0.1:8080/callback", True),
    ("https://user:password@example.org/callback", False),
    ("https://example.org/callback#token", False),
])
def test_readiness_never_claims_connection_or_returns_secrets(redirect, expected):
    result = configuration_status(SimpleNamespace(
        gmail_oauth_client_id="test-client", gmail_oauth_client_secret="test-secret",
        gmail_oauth_redirect_uri=redirect,
    ))
    assert result["configured"] is expected
    assert result["connected"] is False
    assert result["available"] is False
    assert "test-secret" not in str(result)
    assert "test-client" not in str(result)


def test_missing_google_credentials():
    assert not configuration_status(SimpleNamespace(
        gmail_oauth_client_id="", gmail_oauth_client_secret="",
        gmail_oauth_redirect_uri="https://example.org/callback",
    ))["configured"]
