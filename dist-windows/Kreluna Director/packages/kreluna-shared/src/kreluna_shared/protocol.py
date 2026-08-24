from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AgentHello(BaseModel):
    type: Literal["hello"] = "hello"
    device_id: str
    agent_id: str
    hostname: str
    capabilities: list[str]
    display_name: str | None = None
    platform: str = "linux"


class Heartbeat(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    busy: bool = False
    active_task_id: str | None = None


class TaskCommand(BaseModel):
    type: Literal["task"] = "task"
    task_id: str
    capability: str
    goal: str
    args: dict[str, Any] = Field(default_factory=dict)
    grant: str
    timeout_seconds: int = 60


class ControlCommand(BaseModel):
    type: Literal["kill", "pause", "resume"]
    reason: str | None = None


class TaskAck(BaseModel):
    type: Literal["task_ack"] = "task_ack"
    task_id: str


class TaskResult(BaseModel):
    type: Literal["task_result"] = "task_result"
    task_id: str
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class AgentKilled(BaseModel):
    type: Literal["killed"] = "killed"
    device_id: str
    active_task_id: str | None = None


class DashboardEvent(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SignedGrant(BaseModel):
    tenant_id: UUID
    device_id: UUID
    task_id: UUID
    capability: str
    exp: int
    nonce: str
