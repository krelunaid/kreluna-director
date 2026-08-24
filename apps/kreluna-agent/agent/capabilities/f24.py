from __future__ import annotations

from kreluna_shared.crypto import sha256_hex

from agent.tools.render import render_card


def prepare(period: str = "in_scadenza", note: str = "") -> dict:
    image = render_card(
        "PC-F24 — IPSOA (demo)",
        [
            "Lavoro: deleghe F24.",
            f"Periodo: {period}",
            "Programma: creazione in IPSOA, poi Invio Telematico.",
            "",
            "In demo: nessun click su Telematico, nessun invio, nessun pagamento.",
            note[:200],
        ],
    )
    return {
        "ok": True,
        "connected": False,
        "sent": False,
        "period": period,
        "program": "Creazione IPSOA, poi Invio Telematico (in demo non si invia)",
        "message": "Scheda F24 pronta in IPSOA demo. Nessun Invio Telematico.",
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"connected": False, "role": "pc-f24", "program": "IPSOA"},
            }
        ],
    }
