"""Adapter sandbox: usa l'API demo del Director, mai Agenzia delle Entrate."""

from __future__ import annotations

from kreluna_shared.adapters import DraftResult, ObservedInvoice, SubmitResult
from kreluna_shared.crypto import sha256_hex

from agent.tools.automation import prefer_method
from agent.tools.render import render_card


def describe_method() -> str:
    return prefer_method(["api", "ui_automation", "playwright", "mouse"])


def preview_card(title: str, observed: dict) -> bytes:
    return render_card(
        title,
        [
            f"Adapter: Fatture sandbox ({describe_method()})",
            f"Cliente: {observed.get('client')}",
            f"Totale: {observed.get('total_label') or observed.get('total')}",
            f"Stato: {observed.get('status')}",
            "Nessun portale fiscale reale.",
        ],
    )


def hash_png(raw: bytes) -> str:
    return sha256_hex(raw)


def as_draft(data: dict) -> DraftResult:
    return DraftResult(
        draft_id=str(data.get("draft_id") or data.get("id")),
        client=str(data.get("client") or data.get("client_name")),
        net=float(data.get("net") or 0),
        vat=float(data.get("vat") or 0),
        total=float(data.get("total") or 0),
        status=str(data.get("status") or "draft"),
    )


def as_observed(data: dict) -> ObservedInvoice:
    draft = as_draft(data)
    return ObservedInvoice(**draft.model_dump())


def as_submit(data: dict) -> SubmitResult:
    return SubmitResult(draft_id=str(data.get("draft_id")), status=str(data.get("status")))
