from __future__ import annotations

import json
import os
from typing import Any

APP_VERSION = "0.5.4"
STAMP_NAME = "installed_version"


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for item in value.split("."):
        num = "".join(ch for ch in item if ch.isdigit())
        parts.append(int(num or 0))
    return tuple(parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return version_tuple(remote) > version_tuple(local)


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
        "Chiudi Kreluna e reinstalla lo zip nuovo: i dati dello studio restano."
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
