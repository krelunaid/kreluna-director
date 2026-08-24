from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    PAUSED = "paused"
    KILLED = "killed"


class LicenseState(str, Enum):
    ACTIVE = "active"
    GRACE = "grace"
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class Role(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    STUDIO_OWNER = "studio_owner"
    APPROVER = "approver"
    OPERATOR = "operator"
    VIEWER = "viewer"


class EvidenceKind(str, Enum):
    SCREENSHOT = "screenshot"
    STRUCTURED_READ = "structured_read"
    FILE_HASH = "file_hash"
    API_RESPONSE = "api_response"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    APPROVAL = "approval"
    DENY = "deny"
    DENY_LICENSE = "deny_license"


class PlannedTask(BaseModel):
    goal: str
    capability: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk: Risk
    needs_approval: bool = False

    @field_validator("capability")
    @classmethod
    def capability_not_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("capability required")
        return cleaned


class PlanResult(BaseModel):
    ok: bool
    summary: str
    tasks: list[PlannedTask] = Field(default_factory=list)
    denied: bool = False
    deny_reason: str | None = None
    source: str = "deterministic"
    diagnostic: dict[str, str] | None = None
    # Cosa resta da sapere, per capire la risposta che arriva dopo.
    pending: dict[str, Any] | None = None


class TaskSpec(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    requested_by: UUID
    goal: str
    capability: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk: Risk
    status: TaskStatus = TaskStatus.QUEUED
    idempotency_key: str
    assigned_device_id: UUID | None = None


class EvidenceSpec(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    task_id: UUID
    device_id: UUID
    kind: EvidenceKind
    sha256: str
    storage_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPresence(BaseModel):
    device_id: UUID
    agent_id: str
    hostname: str
    display_name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.OFFLINE
    busy: bool = False
    active_task_id: UUID | None = None
    last_seen_at: datetime | None = None
    queue_depth: int = 0
    recent_errors: int = 0
