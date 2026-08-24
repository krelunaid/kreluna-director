"""Una sola lista di PC: la usano sia /agents sia i numeri in alto nella dashboard."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from kreluna_shared.agents import load_live_agent_roles

from app.models import AgentSlot, Device
from app.services.registry import hub, parse_caps


def _from_device(row: Device, slot: AgentSlot | None) -> dict[str, Any]:
    return {
        "device_id": row.id,
        "agent_id": row.agent_id,
        "hostname": row.hostname,
        "display_name": row.display_name,
        "capabilities": parse_caps(row.capabilities),
        "status": row.status,
        "presence": row.presence,
        "busy": row.busy,
        "killed": row.killed,
        "paused": row.paused,
        "platform": row.platform,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "active_task_id": row.active_task_id,
        "connected": row.id in hub.agents,
        "job": slot.job if slot else "",
        "program": slot.program if slot else "",
        "enrollment_code": slot.enrollment_code if slot else "",
    }


def _from_slot(slot: AgentSlot) -> dict[str, Any]:
    return {
        "device_id": slot.id,
        "agent_id": slot.role,
        "hostname": "non-installato",
        "display_name": slot.display_name,
        "capabilities": parse_caps(slot.capabilities),
        "status": "waiting_install",
        "presence": "waiting_install",
        "busy": False,
        "killed": False,
        "paused": False,
        "platform": "windows",
        "last_seen_at": None,
        "active_task_id": None,
        "connected": False,
        "job": slot.job,
        "program": slot.program,
        "enrollment_code": slot.enrollment_code,
    }


def compose_agent_rows(devices: Iterable[Device], slots: Iterable[AgentSlot]) -> list[dict[str, Any]]:
    device_list = list(devices)
    live_roles = {role.role for role in load_live_agent_roles()}
    by_device = {row.id: row for row in device_list}
    by_agent_id = {row.agent_id: row for row in device_list}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in slots:
        live = None
        if slot.device_id and slot.device_id in by_device:
            live = by_device[slot.device_id]
        elif slot.role in by_agent_id:
            live = by_agent_id[slot.role]
        if live is None and slot.role not in live_roles:
            continue
        if live is not None:
            seen.add(live.id)
            rows.append(_from_device(live, slot))
        else:
            rows.append(_from_slot(slot))
    for row in device_list:
        if row.id not in seen:
            rows.append(_from_device(row, None))
    return rows


def count_online(rows: Iterable[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row["connected"] or row["presence"] in {"online", "busy"})
