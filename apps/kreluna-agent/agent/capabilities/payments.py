from __future__ import annotations

from kreluna_shared.crypto import sha256_hex

from agent.tools.render import render_card


def prepare(beneficiary: str = "da definire", reason: str = "pagamento", amount_eur: float = 0) -> dict:
    image = render_card(
        "PC-PAGAMENTI — nessun bonifico",
        [
            "Agent pagamenti: creato e pronto.",
            f"Beneficiario: {beneficiary}",
            f"Causale: {reason[:120]}",
            f"Importo proposto: € {amount_eur:,.2f}",
            "",
            "Stato: BOZZA. Soldi non mossi.",
            "Programma banca/gestionale: da definire.",
        ],
    )
    return {
        "ok": True,
        "connected": False,
        "executed": False,
        "beneficiary": beneficiary,
        "amount_eur": amount_eur,
        "message": "Pagamento solo preparato. Serve il tuo OK e il programma sul PC prima di qualsiasi bonifico.",
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"connected": False, "role": "pc-pagamenti", "executed": False},
            }
        ],
    }


def check_invoices(scope: str = "fatture_da_controllare") -> dict:
    rows = [
        "Rossi Mario — fattura demo 1.830,00 — bozza OK",
        "Verdi Luigi — fattura demo 2.440,00 — da ricontrollare IVA",
        "Nessun invio, nessuna modifica.",
    ]
    image = render_card(
        "PC-PAGAMENTI — controllo fatture (lettura)",
        [f"Scope: {scope}", ""] + rows,
    )
    return {
        "ok": True,
        "connected": False,
        "scope": scope,
        "findings": rows,
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"role": "pc-pagamenti", "readonly": True},
            }
        ],
    }
