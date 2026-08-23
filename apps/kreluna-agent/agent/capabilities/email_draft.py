from __future__ import annotations

from agent.tools.render import render_card
from kreluna_shared.crypto import sha256_hex


def draft(subject: str, body: str, to: str | None = None) -> dict:
    image = render_card(
        "BOZZA EMAIL — non inviata",
        [
            f"A: {to or '(da scegliere)'}",
            f"Oggetto: {subject}",
            "",
            body[:500],
            "",
            "PEC/send disabilitati in questo prototipo.",
        ],
    )
    return {
        "ok": True,
        "draft": {"to": to, "subject": subject, "body": body, "sent": False},
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"sent": False},
            }
        ],
    }
