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


# Il Director sa già quale PC fa che lavoro. Non lo chiede all'utente.
CAPABILITY_TO_ROLE: dict[str, str] = {
    "invoice_prepare_demo": "pc-fatture",
    "invoice_submit_demo": "pc-fatture",
    "notepad_write": "pc-fatture",
    "payment_prepare": "pc-pagamenti",
    "invoice_check": "pc-pagamenti",
    "f24_prepare": "pc-f24",
    "document_check": "pc-documenti",
    "email_draft": "pc-email",
}


def preferred_role(capability: str) -> str | None:
    return CAPABILITY_TO_ROLE.get(capability)


def load_agent_roles(path: str | Path) -> list[AgentRole]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rows = raw.get("agents") or []
    return [AgentRole.model_validate(item) for item in rows]
