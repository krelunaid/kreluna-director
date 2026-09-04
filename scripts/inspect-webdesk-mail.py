"""Inspect recent Webdesk validation format; never print codes or message bodies."""
import asyncio
import base64
import re
import sys
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in ("apps/director-desktop", "apps/director-api", "packages/kreluna-shared/src"):
    sys.path.insert(0, str(ROOT / path))


async def main():
    from kreluna_desktop import prepare_env
    prepare_env()
    import httpx
    from app.config import settings
    from app.database import SessionLocal, engine
    from app.models import GmailConnection
    from app.services.gmail import _google_json, unseal
    from sqlalchemy import select

    async with SessionLocal() as session:
        rows = (await session.execute(select(GmailConnection))).scalars().all()
        if len(rows) != 1:
            print("DIAGNOSTIC_REQUIRES_ONE_CONNECTION")
            return
        row = rows[0]
        refresh = unseal(settings, row.refresh_ciphertext, f"gmail-refresh:{row.tenant_id}")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            tokens = await _google_json(client, "POST", "https://oauth2.googleapis.com/token", data={
                "client_id": settings.gmail_oauth_client_id,
                "client_secret": settings.gmail_oauth_client_secret,
                "refresh_token": refresh, "grant_type": "refresh_token",
            })
            headers = {"Authorization": "Bearer " + tokens["access_token"]}
            base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
            result = await _google_json(client, "GET", base, headers=headers, params={
                "q": 'newer_than:7d webdesk "codice"', "maxResults": 5,
            })
            print("MATCHING_MESSAGES", len(result.get("messages", [])))
            for item in result.get("messages", []):
                message = await _google_json(client, "GET", base + "/" + item["id"], headers=headers,
                                             params={"format": "metadata"})
                fields = {h["name"].lower(): h["value"] for h in message["payload"]["headers"]}
                # No recipient, subject, body, token, message ID or code is output.
                print("SENDER", parseaddr(fields.get("from", ""))[1])
                print("SUBJECT_IS_VALIDATION", "valid" in fields.get("subject", "").lower())
                auth = fields.get("authentication-results", "")
                print("GMAIL_AUTHENTICATED", auth.startswith("mx.google.com;"),
                      "DMARC_PASS", "dmarc=pass" in auth, "DKIM_PASS", "dkim=pass" in auth)
                if parseaddr(fields.get("from", ""))[1] != "noreply@webdesk.it" or "dmarc=pass" not in auth:
                    continue
                full = await _google_json(client, "GET", base + "/" + item["id"], headers=headers,
                                          params={"format": "full"})
                parts = []
                def walk(part, parts=parts):
                    data = part.get("body", {}).get("data", "")
                    if part.get("mimeType") in {"text/plain", "text/html"} and data:
                        parts.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace"))
                    for child in part.get("parts", []):
                        walk(child)
                walk(full["payload"])
                class Text(HTMLParser):
                    def handle_data(self, data):
                        self.pieces.append(data)
                parser = Text()
                parser.pieces = []
                parser.feed(" ".join(parts))
                body = " ".join(parser.pieces)
                print("CODE_WORD_CONTEXT", [re.sub(r"[^\s:]+", lambda m: m[0] if m[0].lower() in {
                    "codice", "di", "sicurezza", "è", "il", "seguente", ":", "webdesk"
                } else f"[len={len(m[0])}]", body[max(0,m.start()-20):m.end()+60])
                    for m in re.finditer(r"codice", body, re.IGNORECASE)])
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:  # noqa: BLE001 -- CLI must not expose provider/credential exceptions.
        print("DIAGNOSTIC_FAILED_NO_SECRETS_LOGGED")
        sys.exit(1)
