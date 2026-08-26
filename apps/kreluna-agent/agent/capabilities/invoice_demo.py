from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

import httpx
from kreluna_shared.workflows import build_invoice_draft

from agent.tools.gestionale import fill_invoice_on_pc


async def prepare(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    sign_request: Callable[[str, dict[str, Any]], dict[str, Any]],
    account_name: str | None = None,
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float = 0.22,
    vat_note: str = "",
    cancel_check: Callable[[], None] | None = None,
    register_process: Callable[[subprocess.Popen], None] | None = None,
) -> dict[str, Any]:
    check = cancel_check or (lambda: None)
    check()
    # Questa capability e' dichiarata demo-only: deve sempre mostrare la
    # finestra locale controllata. Un portale configurato in Fort Knox non
    # deve trasformare silenziosamente una prova in lavoro sul sito reale.
    evidence = fill_invoice_on_pc(
        account_name=account_name or "",
        client_name=client_name,
        description=description,
        net_eur=net_eur,
        vat_rate=vat_rate,
        vat_note=vat_note,
        status="draft",
        cancel_check=check,
        register_process=register_process,
    )
    check()
    path = "/agent/demo-invoice/prepare"
    response = await client.post(
        f"{director_url}{path}",
        json=sign_request(
            path,
            {
                "device_id": device_id,
                "task_id": task_id,
                "account_name": account_name or "",
                "client_name": client_name,
                "description": description,
                "net_eur": net_eur,
                "vat_rate": vat_rate,
                "vat_note": vat_note,
            },
        ),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    draft = build_invoice_draft(
        account_name=account_name or "",
        client_name=client_name,
        description=description,
        net_eur=net_eur,
        vat_rate=vat_rate,
        vat_note=vat_note,
    )
    if evidence:
        evidence[-1]["metadata"]["draft_id"] = data["observed"]["draft_id"]
        evidence[-1]["metadata"]["status"] = "draft"
    return {
        "ok": True,
        **data,
        "method": "ui_visible",
        "program": "PC-FATTURE (prova locale)",
        "live_target": {
            "configured": False,
            "filled": False,
            "sent": False,
            "message": "Prova locale: nessun portale fiscale aperto.",
        },
        "agent": "pc-fatture",
        "draft": draft,
        "evidence": evidence,
    }


async def submit(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    sign_request: Callable[[str, dict[str, Any]], dict[str, Any]],
    draft_id: str,
    client_name: str = "Cliente",
    description: str = "Prestazione",
    net_eur: float = 0.0,
    vat_rate: float = 0.22,
    cancel_check: Callable[[], None] | None = None,
    register_process: Callable[[subprocess.Popen], None] | None = None,
) -> dict[str, Any]:
    check = cancel_check or (lambda: None)
    check()
    path = "/agent/demo-invoice/submit"
    response = await client.post(
        f"{director_url}{path}",
        json=sign_request(
            path,
            {
                "device_id": device_id,
                "task_id": task_id,
                "draft_id": draft_id,
            },
        ),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    check()
    observed = data.get("observed") or {}
    net = float(observed.get("net") or 0)
    evidence = fill_invoice_on_pc(
        client_name=str(observed.get("client") or client_name),
        description=str(observed.get("description") or description),
        net_eur=net if net > 0 else 1.0,
        vat_rate=vat_rate,
        status="issued",
        cancel_check=check,
        register_process=register_process,
    )
    return {
        "ok": True,
        **data,
        "method": "ui_visible",
        "program": "Webdesk / sito Agenzia delle Entrate (demo locale)",
        "agent": "pc-fatture",
        "evidence": evidence,
    }
