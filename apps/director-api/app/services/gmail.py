"""Owner-initiated OAuth. Tokens are never returned to browsers or agents."""

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from kreluna_shared.crypto import decrypt_secret_text, encrypt_secret_text
from sqlalchemy import delete, select, update

from app.models import GmailAuthorization, GmailConnection, User, utcnow

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def configuration_status(config) -> dict:
    redirect = urlsplit(config.gmail_oauth_redirect_uri)
    valid_redirect = (
        redirect.scheme == "https"
        or (redirect.scheme == "http" and redirect.hostname in {"127.0.0.1", "localhost"})
    ) and bool(redirect.hostname) and not (
        redirect.username or redirect.password or redirect.fragment or redirect.query
    )
    desktop = getattr(config, "gmail_oauth_client_type", "web") == "desktop"
    if desktop:
        valid_redirect = valid_redirect and redirect.scheme == "http" and redirect.hostname == "127.0.0.1"
    configured = bool(
        config.gmail_oauth_client_id.strip()
        and (desktop or config.gmail_oauth_client_secret.strip())
        and valid_redirect
    )
    return {
        "configured": configured,
        "connected": False,
        "available": False,
        "scope": GMAIL_SCOPE,
        "message": (
            "Configurazione Google presente. Autorizza l’account per collegarlo."
            if configured else
            "Serve configurare l’app Google OAuth del servizio Kreluna."
        ),
    }


class GmailError(ValueError):
    """Only fixed, user-safe messages; never include provider payloads."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def seal(config, value: str, context: str) -> str:
    return encrypt_secret_text(config.director_credential_key, value, context=context)


def unseal(config, value: str, context: str) -> str:
    return decrypt_secret_text(config.director_credential_key, value, context=context)


async def begin_authorization(session, config, actor, expected_email: str) -> str:
    if not configuration_status(config)["configured"]:
        raise GmailError("Configurazione Google mancante.")
    callback = urlsplit(config.gmail_oauth_redirect_uri)
    if callback.path != "/integrations/gmail/callback":
        raise GmailError("Indirizzo di ritorno Google non configurato correttamente.")
    email = expected_email.strip().lower()
    if not (3 <= len(email) <= 200 and email.count("@") == 1) or any(c.isspace() for c in email):
        raise GmailError("Inserisci l’indirizzo Gmail da collegare.")
    await session.execute(delete(GmailAuthorization).where(
        GmailAuthorization.expires_at <= utcnow(),
    ).execution_options(synchronize_session="fetch"))
    # A second attempt invalidates earlier outstanding requests for this studio.
    await session.execute(update(GmailAuthorization).where(
        GmailAuthorization.tenant_id == actor.tenant_id,
    ).values(consumed=True, invalidated=True, verifier_ciphertext=""))
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    state_hash = digest(state)
    session.add(GmailAuthorization(
        state_hash=state_hash, tenant_id=actor.tenant_id, user_id=actor.user_id,
        expected_email=email, expires_at=utcnow() + timedelta(minutes=5),
        verifier_ciphertext=seal(config, verifier, f"gmail-state:{state_hash}:{actor.tenant_id}"),
    ))
    await session.commit()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": config.gmail_oauth_client_id,
        "redirect_uri": config.gmail_oauth_redirect_uri,
        "response_type": "code", "scope": GMAIL_SCOPE,
        "state": state, "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256", "access_type": "offline",
        "prompt": "consent select_account", "login_hint": email,
    })


async def _google_json(client, method: str, url: str, **kwargs) -> dict:
    try:
        response = await client.request(method, url, **kwargs)
        if response.status_code != 200 or len(response.content) > 100_000:
            raise GmailError("Google non ha completato il collegamento. Riprova da Impostazioni.")
        value = response.json()
        if not isinstance(value, dict):
            raise TypeError()
        return value
    except (httpx.HTTPError, ValueError, TypeError):
        raise GmailError("Google non ha completato il collegamento. Riprova da Impostazioni.") from None


async def complete_authorization(session, config, state: str, code: str, *, client=None) -> None:
    state_hash = digest(state)
    row = await session.get(GmailAuthorization, state_hash)
    if row is None:
        raise GmailError("Collegamento sconosciuto o scaduto. Riprova da Impostazioni.")
    claimed = await session.execute(update(GmailAuthorization).where(
        GmailAuthorization.state_hash == state_hash,
        GmailAuthorization.consumed.is_(False),
        GmailAuthorization.invalidated.is_(False),
        GmailAuthorization.expires_at > utcnow(),
    ).values(consumed=True).execution_options(synchronize_session=False))
    await session.commit()
    if claimed.rowcount != 1:
        raise GmailError("Collegamento già usato o scaduto. Riprova da Impostazioni.")
    owner = (await session.execute(select(User).where(
        User.id == row.user_id, User.tenant_id == row.tenant_id,
        User.role.in_(["studio_owner", "platform_admin"]),
    ))).scalar_one_or_none()
    try:
        verifier = unseal(config, row.verifier_ciphertext, f"gmail-state:{state_hash}:{row.tenant_id}")
    except (ValueError, InvalidTag):
        raise GmailError("Impossibile leggere l’autorizzazione. Riprova da Impostazioni.") from None
    finally:
        row.verifier_ciphertext = ""
        await session.commit()
    if owner is None or not code or len(code) > 4096:
        raise GmailError("Autorizzazione non valida.")
    if client is None:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as owned_client:
            return await _exchange(session, config, row, verifier, code, owned_client)
    return await _exchange(session, config, row, verifier, code, client)


async def _exchange(session, config, row, verifier, code, client) -> None:
    data = {"client_id": config.gmail_oauth_client_id, "code": code,
            "code_verifier": verifier, "grant_type": "authorization_code",
            "redirect_uri": config.gmail_oauth_redirect_uri}
    if config.gmail_oauth_client_secret:
        data["client_secret"] = config.gmail_oauth_client_secret
    tokens = await _google_json(client, "POST", "https://oauth2.googleapis.com/token", data=data)
    access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
    if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
            or GMAIL_SCOPE not in str(tokens.get("scope", "")).split()):
        raise GmailError("Google non ha concesso il collegamento richiesto. Ripeti il consenso.")
    profile = await _google_json(client, "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                                 headers={"Authorization": f"Bearer {access}"})
    email = str(profile.get("emailAddress", "")).lower()
    if email != row.expected_email:
        # Do not connect a different mailbox silently. Discard its grant.
        try:
            await client.post("https://oauth2.googleapis.com/revoke", data={"token": refresh})
        except httpx.HTTPError:
            pass
        raise GmailError("Hai selezionato un altro account Google. Riprova con quello indicato.")
    # Recheck after network I/O: a disconnect or newer attempt must win.
    valid = await session.execute(update(GmailAuthorization).where(
        GmailAuthorization.state_hash == row.state_hash,
        GmailAuthorization.invalidated.is_(False),
        GmailAuthorization.expires_at > utcnow(),
    ).values(consumed=True).execution_options(synchronize_session=False))
    if valid.rowcount != 1:
        await session.rollback()
        raise GmailError("Collegamento annullato. Riprova da Impostazioni.")
    owner = (await session.execute(select(User).where(
        User.id == row.user_id, User.tenant_id == row.tenant_id,
        User.role.in_(["studio_owner", "platform_admin"]),
    ))).scalar_one_or_none()
    if owner is None:
        await session.rollback()
        raise GmailError("Il titolare non è più autorizzato a collegare Gmail.")
    connection = await session.get(GmailConnection, row.tenant_id)
    if connection is None:
        connection = GmailConnection(tenant_id=row.tenant_id)
        session.add(connection)
    connection.email = email
    connection.refresh_ciphertext = seal(config, refresh, f"gmail-refresh:{row.tenant_id}")
    connection.updated_by = row.user_id
    connection.updated_at = utcnow()
    await session.commit()


async def disconnect(session, config, tenant_id: str) -> bool:
    await session.execute(update(GmailAuthorization).where(
        GmailAuthorization.tenant_id == tenant_id,
    ).values(consumed=True, invalidated=True, verifier_ciphertext=""))
    row = await session.get(GmailConnection, tenant_id)
    revoked = True
    if row is not None:
        try:
            token = unseal(config, row.refresh_ciphertext, f"gmail-refresh:{tenant_id}")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
                revoked = response.status_code == 200
        except (httpx.HTTPError, ValueError, InvalidTag):
            revoked = False
        await session.delete(row)
    await session.commit()
    return revoked


async def verify_connection(session, config, tenant_id: str, *, client=None) -> str:
    """Renew without a consent prompt; check identity, never read message bodies."""
    row = await session.get(GmailConnection, tenant_id)
    if row is None:
        raise GmailError("Gmail non è collegato.")
    try:
        refresh = unseal(config, row.refresh_ciphertext, f"gmail-refresh:{tenant_id}")
    except (ValueError, InvalidTag):
        raise GmailError("Collegamento non leggibile. Scollega e ricollega Gmail.") from None
    if client is None:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as owned_client:
            return await _verify(config, row.email, refresh, owned_client)
    return await _verify(config, row.email, refresh, client)


async def _verify(config, email, refresh, client) -> str:
    data = {"client_id": config.gmail_oauth_client_id, "refresh_token": refresh,
            "grant_type": "refresh_token"}
    if config.gmail_oauth_client_secret:
        data["client_secret"] = config.gmail_oauth_client_secret
    tokens = await _google_json(client, "POST", "https://oauth2.googleapis.com/token", data=data)
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise GmailError("Google non ha rinnovato l’accesso. Ricollega Gmail.")
    profile = await _google_json(client, "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                                 headers={"Authorization": f"Bearer {access}"})
    if str(profile.get("emailAddress", "")).lower() != email:
        raise GmailError("Account Gmail non corrispondente. Scollega e ricollega Gmail.")
    return email
