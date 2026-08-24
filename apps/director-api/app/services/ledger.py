from __future__ import annotations

from app.models import InvoiceDraft, new_id


def money_cents(value: float) -> int:
    return round(value * 100)


def format_eur(cents: int) -> str:
    return f"€ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def create_draft(tenant_id: str, client_name: str, description: str, net_eur: float, vat_rate: float) -> InvoiceDraft:
    net = money_cents(net_eur)
    vat = round(net * vat_rate)
    return InvoiceDraft(
        id=new_id(),
        tenant_id=tenant_id,
        client_name=client_name,
        description=description,
        net_cents=net,
        vat_cents=vat,
        total_cents=net + vat,
        status="draft",
    )


def observed_from_draft(draft: InvoiceDraft) -> dict:
    return {
        "draft_id": draft.id,
        "client": draft.client_name,
        "description": draft.description,
        "net": draft.net_cents / 100,
        "vat": draft.vat_cents / 100,
        "total": draft.total_cents / 100,
        "status": draft.status,
        "net_label": format_eur(draft.net_cents),
        "vat_label": format_eur(draft.vat_cents),
        "total_label": format_eur(draft.total_cents),
    }


def verify_invoice(expected: dict, observed: dict) -> dict:
    checks = {
        "client": observed.get("client") == expected.get("client"),
        "net": float(observed.get("net", -1)) == float(expected.get("net", -2)),
        "vat": float(observed.get("vat", -1)) == float(expected.get("vat", -2)),
        "total": float(observed.get("total", -1)) == float(expected.get("total", -2)),
        "status": observed.get("status") == expected.get("status", "draft"),
    }
    return {"ok": all(checks.values()), "checks": checks}
