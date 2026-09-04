import base64
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from app.models import utcnow
from app.services.gmail import GmailError, seal
from app.services.webdesk_mail import extract_code, read_validation_code, trusted_message


def message(body="Login: TESTUSER\nCodice di sicurezza: 123456", **overrides):
    now = utcnow()
    data = {"internalDate": str(int(now.timestamp()*1000)), "payload": {
        "mimeType": "text/plain", "headers": [
            {"name": "From", "value": "noreply@webdesk.it"},
            {"name": "To", "value": "test@example.test"},
            {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass (p=NONE) header.from=webdesk.it;"},
        ], "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}}
    data.update(overrides)
    return data


def test_valid_message_and_exact_login():
    m = message()
    assert trusted_message(m, "test@example.test", utcnow()-timedelta(seconds=1), utcnow())
    assert extract_code(m, "TESTUSER") == "123456"
    with pytest.raises(GmailError):
        extract_code(m, "OTHER")


@pytest.mark.parametrize("kind", ["old", "future", "wrong_recipient", "sender", "fake_auth", "domain", "duplicate_auth", "spam"])
def test_untrusted_metadata_rejected(kind):
    m = message()
    headers = m["payload"]["headers"]
    if kind == "old": m["internalDate"] = "1"
    if kind == "future": m["internalDate"] = str(int((utcnow()+timedelta(minutes=1)).timestamp()*1000))
    if kind == "wrong_recipient": headers[1]["value"] = "other@example.test"
    if kind == "sender": headers[0]["value"] = "noreply@webdesk.it.evil.test"
    if kind == "fake_auth": headers[2]["value"] = "attacker; dmarc=pass header.from=webdesk.it;"
    if kind == "domain": headers[2]["value"] = "mx.google.com; dmarc=pass header.from=webdesk.it.evil;"
    if kind == "duplicate_auth": headers.append(dict(headers[2]))
    if kind == "spam": m["labelIds"] = ["SPAM"]
    assert not trusted_message(m, "test@example.test", utcnow()-timedelta(seconds=1), utcnow())


@pytest.mark.parametrize("body", ["Login: TESTUSER codice: 123456", "Login: TESTUSER Codice di sicurezza: 1234567",
    "Login: TESTUSER Codice di sicurezza: 123456 Codice di sicurezza: 654321"])
def test_missing_or_ambiguous_code(body):
    with pytest.raises(GmailError): extract_code(message(body), "TESTUSER")


async def test_reader_is_narrow_and_refuses_two_messages():
    config = SimpleNamespace(director_credential_key="unit-test-key", gmail_oauth_client_id="fake",
                             gmail_oauth_client_secret="")
    connection = SimpleNamespace(tenant_id="t", email="test@example.test",
        refresh_ciphertext=seal(config, "fake-refresh", "gmail-refresh:t"))
    full_reads = []
    def handle(request):
        if request.url.path == "/token": return httpx.Response(200, json={"access_token": "fake-access"})
        if request.url.path.endswith("/profile"): return httpx.Response(200, json={"emailAddress": connection.email})
        if request.url.path.endswith("/messages"):
            assert "from:noreply@webdesk.it" in request.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": "one"}, {"id": "two"}]})
        full_reads.append(request.url.params["format"])
        return httpx.Response(200, json=message())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(GmailError):
            await read_validation_code(config, connection, utcnow()-timedelta(seconds=1),
                                       utcnow()+timedelta(seconds=1), "TESTUSER", client=client)
    assert full_reads == ["metadata", "metadata"]
