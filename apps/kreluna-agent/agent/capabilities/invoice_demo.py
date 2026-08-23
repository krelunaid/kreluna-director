from __future__ import annotations

from typing import Any

import httpx

from agent.tools.render import render_card
from kreluna_shared.crypto import sha256_hex


def _card(title: str, observed: dict) -> bytes:
    return render_card(
        title,
        [
            f"Cliente: {observed.get('client')}",
            f"Descrizione: {observed.get('description')}",
            f"Imponibile: {observed.get('net_label')}",
            f"IVA: {observed.get('vat_label')}",
            f"Totale: {observed.get('total_label')}",
            f"Stato: {str(observed.get('status', '')).upper()}",
            f"Pratica: {observed.get('draft_id')}",
            "",
            "Gestionale DEMO locale. Nessun invio fiscale.",
        ],
    )


async def prepare(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    signature: str,
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float = 0.22,
) -> dict[str, Any]:
    response = await client.post(
        f"{director_url}/agent/demo-invoice/prepare",
        json={
            "device_id": device_id,
            "task_id": task_id,
            "signature": signature,
            "client_name": client_name,
            "description": description,
            "net_eur": net_eur,
            "vat_rate": vat_rate,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    image = _card("FATTURA DEMO PRONTA — BOZZA", data["observed"])
    return {
        "ok": True,
        **data,
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"status": "draft", "draft_id": data["observed"]["draft_id"]},
            }
        ],
    }


async def submit(
    *,
    client: httpx.AsyncClient,
    director_url: str,
    device_id: str,
    task_id: str,
    signature: str,
    draft_id: str,
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
    image = _card("FATTURA DEMO EMESSA", data["observed"])
    return {
        "ok": True,
        **data,
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"status": "issued", "draft_id": draft_id},
            }
        ],
    }
