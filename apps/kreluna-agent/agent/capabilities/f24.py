from __future__ import annotations

from kreluna_shared.crypto import sha256_hex
from kreluna_shared.f24 import F24PrepareArgs, build_f24_draft

from agent.tools.render import render_card


def prepare(
    client_name: str = "Da indicare",
    taxpayer_id: str = "",
    form_type: str = "ordinary",
    payment_date: str = "",
    lines: list[dict] | None = None,
    period: str = "",
    note: str = "",
    use_saved_access: bool = False,
) -> dict:
    draft = build_f24_draft(
        F24PrepareArgs(
            client_name=client_name,
            taxpayer_id=taxpayer_id,
            form_type=form_type,
            payment_date=payment_date,
            lines=lines or [],
            period=period,
            note=note,
            use_saved_access=use_saved_access,
        )
    )
    totals = draft["totals"]
    rows = [
        f"{line['section_label']} · {line['tax_code']} · {line['reference_year']} · "
        f"€ {line['debit_eur'] or line['credit_eur']:.2f}"
        for line in draft["lines"][:8]
    ]
    state = "BOZZA VALIDATA" if draft["ready_for_review"] else "DATI DA COMPLETARE"
    image = render_card(
        f"PC-F24 — {draft['form_label']}",
        [
            f"Stato: {state}",
            f"Cliente: {draft['client_name']}",
            f"Periodo: {period or 'da verificare'}",
            *rows,
            f"Debiti € {totals['debit_eur']:.2f} · Crediti € {totals['credit_eur']:.2f}",
            f"Saldo € {totals['balance_eur']:.2f}",
            "",
            "SOLO BOZZA: nessun Invio Telematico e nessun pagamento.",
            note[:200],
        ],
    )
    return {
        "ok": True,
        "connected": False,
        "sent": False,
        "payment_started": False,
        "period": period,
        "program": "Preparazione controllata; Invio Telematico escluso",
        "draft": draft,
        "message": (
            f"{draft['form_label']} validato e pronto per il controllo umano. "
            "Nessun invio e nessun pagamento."
            if draft["ready_for_review"]
            else "Scheda F24 aperta, ma mancano dati obbligatori. Nessun invio e nessun pagamento."
        ),
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {
                    "connected": False,
                    "role": "pc-f24",
                    "program": "F24 review",
                    "ready_for_review": draft["ready_for_review"],
                    "sent": False,
                },
            }
        ],
    }
