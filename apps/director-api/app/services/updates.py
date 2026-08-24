from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx
from kreluna_shared.update import APP_VERSION, release_status, unavailable_status

from app.config import settings

CACHE_SECONDS = 15 * 60
_cached_at = 0.0
_cached_status: dict[str, Any] | None = None


def _allowed_channel_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme == "https":
        return True
    return not settings.is_production and parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }


async def latest_update_status(*, force: bool = False) -> dict[str, Any]:
    """Controlla la release pubblica. Un guasto non blocca mai il Director."""

    global _cached_at, _cached_status
    now = time.monotonic()
    if not force and _cached_status is not None and now - _cached_at < CACHE_SECONDS:
        return dict(_cached_status)

    url = settings.kreluna_update_api_url.strip()
    if not _allowed_channel_url(url):
        result = unavailable_status(APP_VERSION)
    else:
        try:
            async with httpx.AsyncClient(
                timeout=8,
                follow_redirects=True,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"Kreluna-Director/{APP_VERSION}",
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            result = release_status(payload if isinstance(payload, dict) else {}, APP_VERSION)
        except (httpx.HTTPError, ValueError, TypeError):
            result = unavailable_status(APP_VERSION)

    _cached_at = now
    _cached_status = dict(result)
    return result
