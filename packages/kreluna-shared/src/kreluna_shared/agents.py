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


def load_agent_roles(path: str | Path) -> list[AgentRole]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rows = raw.get("agents") or []
    return [AgentRole.model_validate(item) for item in rows]
