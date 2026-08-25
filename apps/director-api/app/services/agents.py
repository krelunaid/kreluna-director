"""Una sola lista di PC: la usano sia /agents sia i numeri in alto nella dashboard."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from kreluna_shared.agents import capabilities_for_role, load_live_agent_roles, platforms_for_role

from app.models import AgentSlot, Device
from app.services.registry import hub, parse_caps


def _needs_update(row: Device) -> bool:
    """Il PC dichiara meno lavori di quelli del suo ruolo: ha un Agent vecchio."""

    wanted = set(capabilities_for_role(row.agent_id))
    if not wanted:
        return False
    return bool(wanted - set(parse_caps(row.capabilities)))


def _from_device(row: Device, slot: AgentSlot | None, retired: bool = False) -> dict[str, Any]:
    return {
        "retired": retired,
        "needs_update": _needs_update(row),
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
        "enrollment_required": not bool(slot and slot.device_id),
        "supported_platforms": platforms_for_role(row.agent_id),
    }


def _from_slot(slot: AgentSlot) -> dict[str, Any]:
    return {
        "retired": False,
        "needs_update": False,
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
        "platform": "not_installed",
        "last_seen_at": None,
        "active_task_id": None,
        "connected": False,
        "job": slot.job,
        "program": slot.program,
        "enrollment_required": True,
        "supported_platforms": platforms_for_role(slot.role),
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
        # Un ruolo vecchio si mostra solo mentre quel PC è davvero collegato.
        if slot.role not in live_roles and (live is None or live.id not in hub.agents):
            continue
        if live is not None:
            seen.add(live.id)
            rows.append(_from_device(live, slot, retired=slot.role not in live_roles))
        else:
            rows.append(_from_slot(slot))
    for row in device_list:
        if row.id not in seen:
            rows.append(_from_device(row, None, retired=row.agent_id not in live_roles))
    return rows


def count_online(rows: Iterable[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row["connected"] or row["presence"] in {"online", "busy"})
