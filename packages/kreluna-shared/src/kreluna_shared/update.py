from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

APP_VERSION = "0.5.13"
STAMP_NAME = "installed_version"
DEFAULT_UPDATE_API = "https://api.github.com/repos/krelunaid/kreluna-director/releases/latest"
DEFAULT_RELEASE_PAGE = "https://github.com/krelunaid/kreluna-director/releases/latest"
RELEASE_FILENAMES = {
    "macos": "Kreluna-Director-Mac.zip",
    "windows": "Kreluna-Director-Windows.zip",
}
TRUSTED_RELEASE_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for item in value.split("."):
        num = "".join(ch for ch in item if ch.isdigit())
        parts.append(int(num or 0))
    return tuple(parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return version_tuple(remote) > version_tuple(local)


def platform_key(value: str | None = None) -> str:
    current = (value or sys.platform).lower()
    if current.startswith(("darwin", "macos")):
        return "macos"
    if current.startswith(("win", "windows")):
        return "windows"
    return "unknown"


def trusted_release_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in TRUSTED_RELEASE_HOSTS:
        return ""
    return url


def release_status(
    release: dict[str, Any],
    local: str = APP_VERSION,
    platform: str | None = None,
) -> dict[str, Any]:
    """Converte una GitHub Release nel solo stato sicuro mostrato dalla UI."""

    latest = str(release.get("tag_name") or release.get("version") or "").strip().lstrip("vV")
    system = platform_key(platform)
    release_url = trusted_release_url(release.get("html_url")) or DEFAULT_RELEASE_PAGE
    filename = RELEASE_FILENAMES.get(system, "")
    download_url = ""
    checksum_url = ""
    assets = release.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            url = trusted_release_url(asset.get("browser_download_url"))
            if name == filename:
                download_url = url
            elif filename and name == f"{filename}.sha256":
                checksum_url = url
    notes = str(release.get("body") or release.get("notes") or "").strip()[:4000]
    ignored = bool(release.get("draft")) or bool(release.get("prerelease"))
    available = bool(latest and not ignored and is_newer(latest, local))
    return {
        "state": "available" if available else "current",
        "available": available,
        "current_version": local,
        "latest_version": latest or local,
        "notes": notes,
        "platform": system,
        "download_url": download_url or (release_url if available else ""),
        "checksum_url": checksum_url,
        "release_url": release_url,
        "published_at": str(release.get("published_at") or ""),
    }


def unavailable_status(local: str = APP_VERSION, platform: str | None = None) -> dict[str, Any]:
    return {
        "state": "unavailable",
        "available": False,
        "current_version": local,
        "latest_version": local,
        "notes": "",
        "platform": platform_key(platform),
        "download_url": "",
        "checksum_url": "",
        "release_url": DEFAULT_RELEASE_PAGE,
        "published_at": "",
    }


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def manifest_payload() -> dict[str, Any]:
    return {
        "version": APP_VERSION,
        "min_version": "0.3.0",
        "channel": os.environ.get("KRELUNA_UPDATE_CHANNEL", "stable"),
        "notes": "Programma installabile Mac e Windows: Python è già dentro, non si installa a parte.",
        "packages": {
            "macos": {
                "filename": "Kreluna-Director-Mac.zip",
                "url": os.environ.get("KRELUNA_UPDATE_MAC_URL", ""),
                "sha256": os.environ.get("KRELUNA_UPDATE_MAC_SHA256", ""),
            },
            "windows": {
                "filename": "Kreluna-Director-Windows.zip",
                "url": os.environ.get("KRELUNA_UPDATE_WIN_URL", ""),
                "sha256": os.environ.get("KRELUNA_UPDATE_WIN_SHA256", ""),
            },
        },
    }


def sign_manifest(seed: str, payload: dict[str, Any]) -> str:
    from kreluna_shared.crypto import b64e, server_private_from_seed

    return b64e(server_private_from_seed(seed).sign(_canonical(payload)))


def verify_manifest(public_or_seed: str | bytes, payload: dict[str, Any], signature: str) -> bool:
    from kreluna_shared.crypto import b64d, server_public_bytes, verify_bytes

    public = public_or_seed if isinstance(public_or_seed, bytes) else server_public_bytes(public_or_seed)
    try:
        return verify_bytes(public, _canonical(payload), b64d(signature))
    except Exception:
        return False


def evaluate_update(manifest: dict[str, Any], local: str = APP_VERSION) -> str | None:
    remote = str(manifest.get("version") or "")
    if not remote or not is_newer(remote, local):
        return None
    notes = str(manifest.get("notes") or "").strip()
    extra = f" {notes}" if notes else ""
    return (
        f"È disponibile la versione {remote} (ora hai {local}).{extra} "
        "Apri Kreluna e scegli Scarica e aggiorna: i dati dello studio restano."
    )


def read_installed_version(support_dir: Any, stamp_name: str = STAMP_NAME) -> str:
    from pathlib import Path

    path = Path(support_dir) / stamp_name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_installed_version(support_dir: Any, version: str = APP_VERSION, stamp_name: str = STAMP_NAME) -> None:
    from pathlib import Path

    path = Path(support_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / stamp_name).write_text(version + "\n", encoding="utf-8")


def runtime_needs_refresh(support_dir: Any, version: str = APP_VERSION) -> bool:
    return read_installed_version(support_dir) != version
