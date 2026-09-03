"""Gmail connector readiness. No mailbox access until OAuth is implemented."""

from urllib.parse import urlsplit

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def configuration_status(config) -> dict:
    redirect = urlsplit(config.gmail_oauth_redirect_uri)
    valid_redirect = (
        redirect.scheme == "https"
        or (redirect.scheme == "http" and redirect.hostname in {"127.0.0.1", "localhost"})
    ) and bool(redirect.hostname) and not (
        redirect.username or redirect.password or redirect.fragment or redirect.query
    )
    configured = bool(
        config.gmail_oauth_client_id.strip()
        and config.gmail_oauth_client_secret.strip()
        and valid_redirect
    )
    return {
        "configured": configured,
        "connected": False,
        "available": False,
        "scope": GMAIL_SCOPE,
        "message": (
            "Configurazione Google presente. Collegamento OAuth ancora da completare."
            if configured else
            "Serve configurare l’app Google OAuth del servizio Kreluna."
        ),
    }
