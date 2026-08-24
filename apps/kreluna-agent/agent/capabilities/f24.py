from __future__ import annotations

from agent.tools.render import render_card
from kreluna_shared.crypto import sha256_hex


def prepare(period: str = "in_scadenza", note: str = "") -> dict:
    image = render_card(
        "PC-F24 — programma non collegato",
        [
            "Agent: creato e pronto.",
            "Lavoro: preparare F24, senza inviare.",
            f"Periodo: {period}",
            "Programma: da definire (Agenzia delle Entrate).",
            "",
            "Nessun click, nessun invio, nessun pagamento.",
            note[:200],
        ],
    )
    return {
        "ok": True,
        "connected": False,
        "period": period,
        "program": "da definire",
        "message": "Agent PC-F24 esiste. Manca solo il programma da usare su quel PC.",
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"connected": False, "role": "pc-f24"},
            }
        ],
    }
