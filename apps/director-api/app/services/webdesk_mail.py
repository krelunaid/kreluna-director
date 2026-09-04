"""Narrow Webdesk validation reader. Email is data, never agent instructions."""
import base64
import re
from datetime import datetime
from email.utils import getaddresses
from html.parser import HTMLParser
from urllib.parse import quote

import httpx

from app.services.gmail import GmailError, _google_json, unseal

SENDER = "noreply@webdesk.it"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pieces = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.pieces.append(data)


def headers_of(message):
    headers = {}
    for header in message.get("payload", {}).get("headers", []):
        headers.setdefault(header["name"].lower(), []).append(header["value"])
    return headers


def trusted_message(message, recipient: str, since: datetime, now: datetime) -> bool:
    headers = headers_of(message)
    try:
        received = int(message["internalDate"])
    except (ValueError, KeyError, TypeError):
        return False
    if not int(since.timestamp()*1000) <= received <= int(now.timestamp()*1000):
        return False
    if set(message.get("labelIds", [])) & {"SPAM", "TRASH"}:
        return False
    senders = getaddresses(headers.get("from", []))
    recipients = getaddresses(headers.get("to", []))
    if len(senders) != 1 or senders[0][1].lower() != SENDER:
        return False
    if recipient.lower() not in {address.lower() for _, address in recipients}:
        return False
    # Gmail's receiving authentication result, not an arbitrary sender header.
    auth = [value for value in headers.get("authentication-results", [])
            if value.lstrip().startswith("mx.google.com;")]
    return len(auth) == 1 and bool(re.search(
        r"\bdmarc=pass\b[^;]*\bheader\.from=webdesk\.it(?:[;\s]|$)", auth[0], re.IGNORECASE
    ))


def extract_code(message, expected_login: str) -> str:
    texts = []
    def walk(part, depth=0):
        if depth > 8 or part.get("filename"):
            return
        data = part.get("body", {}).get("data", "")
        if part.get("mimeType") in {"text/plain", "text/html"} and data:
            if len(data) > 100_000:
                raise GmailError("Messaggio Webdesk non riconosciuto.")
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")
            except (ValueError, UnicodeError):
                raise GmailError("Messaggio Webdesk non riconosciuto.") from None
            parser = _Text()
            parser.feed(decoded)
            texts.append(" ".join(parser.pieces))
        for child in part.get("parts", []):
            walk(child, depth+1)
    walk(message.get("payload", {}))
    text = " ".join(texts)
    logins = set(re.findall(r"\blogin\s*:\s*([^\s]+)", text, re.IGNORECASE))
    if not expected_login or logins != {expected_login}:
        raise GmailError("Il codice non corrisponde all’accesso Webdesk richiesto.")
    codes = set(re.findall(r"\bcodice\s+di\s+sicurezza\s*:\s*([A-Za-z0-9]{6})\b", text, re.IGNORECASE))
    if len(codes) != 1:
        raise GmailError("Codice Webdesk mancante o ambiguo. Nessun codice inserito.")
    return codes.pop()


async def read_validation_code(config, connection, since: datetime, now: datetime, expected_login: str, *, client=None):
    """Return (message_id, code) in memory only, or None while awaiting delivery."""
    if client is None:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as owned:
            return await read_validation_code(config, connection, since, now, expected_login, client=owned)
    refresh = unseal(config, connection.refresh_ciphertext, f"gmail-refresh:{connection.tenant_id}")
    tokens = await _google_json(client, "POST", "https://oauth2.googleapis.com/token", data={
        "client_id": config.gmail_oauth_client_id, "client_secret": config.gmail_oauth_client_secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    })
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise GmailError("Accesso Gmail non disponibile.")
    headers = {"Authorization": "Bearer " + access}
    profile = await _google_json(client, "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", headers=headers)
    if profile.get("emailAddress", "").lower() != connection.email:
        raise GmailError("Account Gmail non corrispondente.")
    base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    result = await _google_json(client, "GET", base, headers=headers, params={
        "q": f'from:{SENDER} after:{int(since.timestamp())} "codice di sicurezza"',
        "maxResults": 5, "includeSpamTrash": False,
    })
    if result.get("nextPageToken"):
        raise GmailError("Troppe richieste Webdesk contemporanee. Mi fermo.")
    matches = []
    for item in result.get("messages", []):
        mid = item.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", mid):
            raise GmailError("Risposta Gmail non riconosciuta.")
        message = await _google_json(client, "GET", base + "/" + quote(mid), headers=headers, params={"format": "metadata"})
        if trusted_message(message, connection.email, since, now):
            matches.append(mid)
    if not matches:
        return None
    if len(matches) != 1:
        raise GmailError("Più codici Webdesk ricevuti: mi fermo senza sceglierne uno.")
    message = await _google_json(client, "GET", base + "/" + quote(matches[0]), headers=headers, params={"format": "full"})
    if not trusted_message(message, connection.email, since, now):
        raise GmailError("Messaggio Webdesk non verificato.")
    return matches[0], extract_code(message, expected_login)
