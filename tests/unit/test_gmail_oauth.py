from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.database import Base
from app.models import GmailAuthorization, GmailConnection, Tenant, User, utcnow
from app.services.gmail import (
    GMAIL_SCOPE,
    GmailError,
    begin_authorization,
    complete_authorization,
    digest,
    disconnect,
    pkce_challenge,
    unseal,
    verify_connection,
)
from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def oauth():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    config = SimpleNamespace(
        gmail_oauth_client_id="test-client", gmail_oauth_client_secret="",
        gmail_oauth_client_type="desktop",
        gmail_oauth_redirect_uri="http://127.0.0.1:8080/integrations/gmail/callback",
        director_credential_key="test-key-used-only-in-isolated-unit-tests",
    )
    actor = SimpleNamespace(tenant_id="studio-a", user_id="owner-a")
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Tenant(id=actor.tenant_id, name="Test", slug="test"))
        session.add(User(id=actor.user_id, tenant_id=actor.tenant_id,
                         role="studio_owner", email="owner@example.test", name="Test"))
        await session.commit()
        yield session, config, actor
    await engine.dispose()


async def start(oauth):
    session, config, actor = oauth
    url = await begin_authorization(session, config, actor, "mailbox@example.test")
    return parse_qs(urlsplit(url).query)


def google_client(*, email="mailbox@example.test", scope=GMAIL_SCOPE, calls=None):
    def handle(request):
        if calls is not None:
            calls.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-access", "refresh_token": "fake-refresh", "scope": scope})
        if request.url.path == "/gmail/v1/users/me/profile":
            return httpx.Response(200, json={"emailAddress": email})
        if request.url.path == "/revoke":
            return httpx.Response(200)
        raise AssertionError("Unexpected Google endpoint")
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_pkce_ciphertext_and_tenant_context(oauth):
    session, config, actor = oauth
    query = await start(oauth)
    state = query["state"][0]
    row = await session.get(GmailAuthorization, digest(state))
    verifier = unseal(config, row.verifier_ciphertext, f"gmail-state:{digest(state)}:{actor.tenant_id}")
    assert query["code_challenge"] == [pkce_challenge(verifier)]
    assert query["code_challenge_method"] == ["S256"]
    assert verifier not in row.verifier_ciphertext
    assert state != row.state_hash
    calls = []
    async with google_client(calls=calls) as client:
        await complete_authorization(session, config, state, "fake-code", client=client)
    connection = await session.get(GmailConnection, actor.tenant_id)
    assert "fake-refresh" not in connection.refresh_ciphertext
    assert unseal(config, connection.refresh_ciphertext, f"gmail-refresh:{actor.tenant_id}") == "fake-refresh"
    assert row.verifier_ciphertext == ""
    assert len(calls) == 2  # No email body is read by the connection flow.
    with pytest.raises(InvalidTag):
        unseal(config, connection.refresh_ciphertext, "gmail-refresh:another-studio")


@pytest.mark.parametrize("reason", ["expired", "replay", "cancelled", "owner_removed", "new_attempt"])
async def test_invalid_authorizations_cannot_connect(oauth, reason):
    session, config, actor = oauth
    query = await start(oauth)
    state = query["state"][0]
    row = await session.get(GmailAuthorization, digest(state))
    if reason == "expired":
        row.expires_at = utcnow() - timedelta(seconds=1)
    elif reason == "replay":
        row.consumed = True
    elif reason == "cancelled":
        await disconnect(session, config, actor.tenant_id)
    elif reason == "owner_removed":
        owner = await session.get(User, actor.user_id)
        owner.role = "employee"
    elif reason == "new_attempt":
        await start(oauth)
    await session.commit()
    calls = []
    async with google_client(calls=calls) as client:
        with pytest.raises(GmailError):
            await complete_authorization(session, config, state, "fake-code", client=client)
    assert not calls
    assert await session.get(GmailConnection, actor.tenant_id) is None


@pytest.mark.parametrize("email,scope", [("wrong@example.test", GMAIL_SCOPE), ("mailbox@example.test", "openid")])
async def test_wrong_account_or_missing_scope_not_saved(oauth, email, scope):
    session, config, actor = oauth
    state = (await start(oauth))["state"][0]
    async with google_client(email=email, scope=scope) as client:
        with pytest.raises(GmailError):
            await complete_authorization(session, config, state, "fake-code", client=client)
    assert await session.get(GmailConnection, actor.tenant_id) is None


async def test_replay_after_success_does_not_call_google(oauth):
    session, config, _actor = oauth
    state = (await start(oauth))["state"][0]
    calls = []
    async with google_client(calls=calls) as client:
        await complete_authorization(session, config, state, "fake-code", client=client)
        with pytest.raises(GmailError):
            await complete_authorization(session, config, state, "fake-code", client=client)
    assert len(calls) == 2
    assert len((await session.execute(select(GmailConnection))).scalars().all()) == 1


async def test_refresh_checks_identity_without_new_authorization(oauth):
    session, config, actor = oauth
    state = (await start(oauth))["state"][0]
    async with google_client() as client:
        await complete_authorization(session, config, state, "fake-code", client=client)
    calls = []
    async with google_client(calls=calls) as client:
        assert await verify_connection(session, config, actor.tenant_id, client=client) == "mailbox@example.test"
    assert len(calls) == 2
    assert b"grant_type=refresh_token" in calls[0].content
    assert b"code_verifier" not in calls[0].content


async def test_wrong_identity_on_refresh_is_rejected(oauth):
    session, config, actor = oauth
    state = (await start(oauth))["state"][0]
    async with google_client() as client:
        await complete_authorization(session, config, state, "fake-code", client=client)
    async with google_client(email="wrong@example.test") as client:
        with pytest.raises(GmailError):
            await verify_connection(session, config, actor.tenant_id, client=client)
