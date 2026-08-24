from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AgentRole(BaseModel):
    role: str
    display_name: str
    job: str
    program: str = "da definire"
    capabilities: list[str] = Field(default_factory=list)
    retired: bool = False


# Il Director sa già quale PC fa che lavoro. Non lo chiede all'utente.
CAPABILITY_TO_ROLE: dict[str, str] = {
    "invoice_prepare_demo": "pc-fatture",
    "invoice_submit_demo": "pc-fatture",
    "notepad_write": "pc-fatture",
    "payment_prepare": "pc-pagamenti",
    "invoice_check": "pc-contabilita",
    "f24_prepare": "pc-f24",
    "contabilita_prepare": "pc-contabilita",
    "camera_prepare": "pc-camerali",
    "contratti_prepare": "pc-contratti",
    "durc_prepare": "pc-durc",
    "visure_prepare": "pc-visure",
    "document_check": "pc-visure",
    "email_draft": "pc-email",
}


def preferred_role(capability: str, args: dict | None = None) -> str | None:
    """Quale PC deve farlo. Per i portali veri dipende dal portale chiesto."""

    if capability in {"portal_open", "portal_learn"}:
        from kreluna_shared.programs import portal_for_key

        portal = portal_for_key(str((args or {}).get("portal") or ""))
        return portal.role if portal else None
    return CAPABILITY_TO_ROLE.get(capability)


def capabilities_for_role(role: str, path: str | Path | None = None) -> list[str]:
    roles = load_agent_roles(path or default_agents_path())
    for item in roles:
        if item.role == role:
            return list(item.capabilities)
    return []


def default_agents_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "policies" / "agents.yaml"
        if candidate.exists():
            return candidate
    return Path("policies/agents.yaml")


def load_agent_roles(path: str | Path | None = None) -> list[AgentRole]:
    raw = yaml.safe_load(Path(path or default_agents_path()).read_text(encoding="utf-8")) or {}
    rows = raw.get("agents") or []
    return [AgentRole.model_validate(item) for item in rows]


def load_live_agent_roles(path: str | Path | None = None) -> list[AgentRole]:
    return [item for item in load_agent_roles(path or default_agents_path()) if not item.retired]
