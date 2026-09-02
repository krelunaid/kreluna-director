"""Programmi veri dello studio: indirizzi e campi, letti da policies/programs.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field


class Portal(BaseModel):
    key: str
    role: str
    name: str
    url: str
    field: str = ""
    username_field: str = ""
    password_field: str = ""
    login_note: str = ""
    configured: bool = True
    app_path: str = ""
    customer_search_fields: dict[str, str] = Field(default_factory=dict)
    customer_create_fields: dict[str, str] = Field(default_factory=dict)
    invoice_fields: dict[str, str] = Field(default_factory=dict)


class PortalSettings(BaseModel):
    wait_for_login_seconds: int = Field(default=60, ge=0, le=600)
    poll_seconds: int = Field(default=3, ge=1, le=60)
    mac_browser: str = "Google Chrome"


def default_programs_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "policies" / "programs.yaml"
        if candidate.exists():
            return candidate
    return Path("policies/programs.yaml")


def _raw(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or default_programs_path()).read_text(encoding="utf-8")) or {}


def load_portals(path: str | Path | None = None) -> list[Portal]:
    rows = (_raw(path).get("portals") or {}).items()
    return [Portal(key=key, **(value or {})) for key, value in rows]


def load_settings(path: str | Path | None = None) -> PortalSettings:
    return PortalSettings.model_validate(_raw(path).get("settings") or {})


def portal_for_key(key: str, path: str | Path | None = None) -> Portal | None:
    for portal in load_portals(path):
        if portal.key == key:
            if key == "fatture-webdesk":
                target = os.environ.get("KRELUNA_FATTURE_TARGET", "").strip()
                target_file = os.environ.get("KRELUNA_FATTURE_TARGET_FILE", "").strip()
                if not target and target_file:
                    try:
                        target = Path(target_file).read_text(encoding="utf-8-sig").strip()
                    except (OSError, UnicodeDecodeError):
                        target = ""
                if target:
                    parsed = urlparse(target)
                    if parsed.scheme in {"https", "http"} and parsed.hostname:
                        return portal.model_copy(
                            update={"url": target, "app_path": "", "configured": True}
                        )
                    return portal.model_copy(
                        update={"app_path": target, "configured": True}
                    )
            return portal
    return None


def portals_for_role(role: str, path: str | Path | None = None) -> list[Portal]:
    return [portal for portal in load_portals(path) if portal.role == role]
