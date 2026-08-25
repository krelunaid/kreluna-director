from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agent.capabilities.portal import prepare_invoice_portal
from agent.tools.gestionale import fill_invoice_on_pc


async def prepare(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    signature: str,
    account_name: str | None = None,
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float = 0.22,
    vat_note: str = "",
) -> dict[str, Any]:
    live = await asyncio.to_thread(
        prepare_invoice_portal,
        account_name=account_name or "",
        client_name=client_name,
        description=description,
        net_eur=net_eur,
        vat_rate=vat_rate,
        vat_note=vat_note,
    )
    evidence = list(live.get("evidence") or [])
    if not live.get("filled"):
        evidence.extend(
            fill_invoice_on_pc(
                account_name=account_name or "",
                client_name=client_name,
                description=description,
                net_eur=net_eur,
                vat_rate=vat_rate,
                vat_note=vat_note,
                status="draft",
            )
        )
    response = await client.post(
        f"{director_url}/agent/demo-invoice/prepare",
        json={
            "device_id": device_id,
            "task_id": task_id,
            "signature": signature,
            "account_name": account_name or "",
            "client_name": client_name,
            "description": description,
            "net_eur": net_eur,
            "vat_rate": vat_rate,
            "vat_note": vat_note,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if evidence:
        evidence[-1]["metadata"]["draft_id"] = data["observed"]["draft_id"]
        evidence[-1]["metadata"]["status"] = "draft"
    return {
        "ok": True,
        **data,
        "method": "portal_fields_visible" if live.get("filled") else "ui_visible",
        "program": live.get("program") or "PC-FATTURE (prova locale)",
        "live_target": {
            "configured": bool(live.get("configured")),
            "filled": bool(live.get("filled")),
            "sent": False,
            "message": live.get("message") or "",
        },
        "agent": "pc-fatture",
        "evidence": evidence,
    }


async def submit(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    signature: str,
    draft_id: str,
    client_name: str = "Cliente",
    description: str = "Prestazione",
    net_eur: float = 0.0,
    vat_rate: float = 0.22,
) -> dict[str, Any]:
    response = await client.post(
        f"{director_url}/agent/demo-invoice/submit",
        json={
            "device_id": device_id,
            "task_id": task_id,
            "signature": signature,
            "draft_id": draft_id,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    observed = data.get("observed") or {}
    net = float(observed.get("net") or 0)
    evidence = fill_invoice_on_pc(
        client_name=str(observed.get("client") or client_name),
        description=str(observed.get("description") or description),
        net_eur=net if net > 0 else 1.0,
        vat_rate=vat_rate,
        status="issued",
    )
    return {
        "ok": True,
        **data,
        "method": "ui_visible",
        "program": "Webdesk / sito Agenzia delle Entrate (demo locale)",
        "agent": "pc-fatture",
        "evidence": evidence,
    }
