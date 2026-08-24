from __future__ import annotations

from kreluna_shared.crypto import sha256_hex

from agent.tools.render import render_card

MISSING = [
    {"client": "Bianchi Laura", "document": "Visura camerale", "age_days": 18},
    {"client": "Verdi Holding", "document": "Documento identità", "age_days": 7},
    {"client": "Neri & Figli", "document": "Delega F24", "age_days": 3},
]


def check(scope: str = "missing_documents") -> dict:
    image = render_card(
        "DOCUMENTI MANCANTI — sola lettura",
        [f"{row['client']}: {row['document']} ({row['age_days']} giorni)" for row in MISSING]
        + ["", f"Scope: {scope}", "Nessun file è stato modificato."],
    )
    return {
        "ok": True,
        "scope": scope,
        "missing": MISSING,
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"count": len(MISSING)},
            }
        ],
    }
