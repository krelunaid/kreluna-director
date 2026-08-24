"""Schede demo dei programmi dello studio. Nessun SPID, smart card o invio reale."""

from __future__ import annotations

from agent.tools.render import render_card
from kreluna_shared.crypto import sha256_hex

SPECS: dict[str, dict[str, str]] = {
    "contabilita_prepare": {
        "title": "PC-CONTABILITA — IPSOA (demo)",
        "role": "pc-contabilita",
        "program": "Scarico AdE XML/P7M → carico IPSOA → importatore contabile",
        "message": "Scheda contabilità pronta. Nessun accesso AdE o IPSOA reale.",
        "steps": (
            "1. Scarico fatture AdE (utenza cliente SPID / smart card)\n"
            "2. File XML / P7M sul PC\n"
            "3. Carico in IPSOA\n"
            "4. Importatore contabile IPSOA\n"
            "\n"
            "SPID / smart card NON usati. Nessuno scarico reale."
        ),
    },
    "camera_prepare": {
        "title": "PC-CAMERALI — CGN / ComUnica (demo)",
        "role": "pc-camerali",
        "program": "Sito CGN → Desktop ComUnica",
        "message": "Scheda pratica camerale pronta. Nessun invio.",
        "steps": (
            "1. Apri il sito CGN\n"
            "2. Compila la pratica\n"
            "3. Completa su Desktop ComUnica\n"
            "4. Attendi approvazione umana prima di qualsiasi invio"
        ),
    },
    "contratti_prepare": {
        "title": "PC-CONTRATTI — AdE Samuele (demo)",
        "role": "pc-contratti",
        "program": "Sito Agenzia delle Entrate (utenza Samuele)",
        "message": "Scheda contratto pronta. Nessun invio all'Agenzia.",
        "steps": (
            "1. Apri il sito AdE con l'utenza di Samuele\n"
            "2. Seleziona il tipo di contratto\n"
            "3. Compila i dati del cliente\n"
            "4. Attendi approvazione umana prima di qualsiasi invio"
        ),
    },
    "durc_prepare": {
        "title": "PC-DURC — INPS (demo)",
        "role": "pc-durc",
        "program": "Sito INPS (utenza cliente smart card / SPID)",
        "message": "Scheda DURC pronta. Nessun accesso INPS reale.",
        "steps": (
            "1. Apri il sito INPS con l'utenza del cliente\n"
            "2. Seleziona richiesta DURC\n"
            "3. Controlla anagrafica\n"
            "4. Attendi approvazione umana — non inviare"
        ),
    },
    "visure_prepare": {
        "title": "PC-VISURE — CGN (demo)",
        "role": "pc-visure",
        "program": "Sito CGN",
        "message": "Scheda visura pronta. Nessun download reale.",
        "steps": (
            "1. Apri il sito CGN\n"
            "2. Cerca l'impresa / persona\n"
            "3. Seleziona il tipo di visura\n"
            "4. Attendi approvazione umana prima del download"
        ),
    },
}


def _prepare(
    kind: str,
    *,
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    spec = SPECS[kind]
    extra = period or practice_type or contract_type or visura_type or "—"
    image = render_card(
        spec["title"],
        [
            f"Cliente: {client_name}",
            f"Dettaglio: {extra}",
            f"Programma: {spec['program']}",
            "",
            *spec["steps"].split("\n"),
            notes[:200],
        ],
    )
    return {
        "ok": True,
        "demo": True,
        "sent": False,
        "spid_used": False,
        "smart_card_used": False,
        "client_name": client_name,
        "program": spec["program"],
        "message": spec["message"],
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"connected": False, "role": spec["role"], "program": spec["program"]},
            }
        ],
    }


def contabilita(
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    return _prepare(
        "contabilita_prepare",
        client_name=client_name,
        notes=notes,
        period=period,
        practice_type=practice_type,
        contract_type=contract_type,
        visura_type=visura_type,
    )


def camera(
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    return _prepare(
        "camera_prepare",
        client_name=client_name,
        notes=notes,
        period=period,
        practice_type=practice_type,
        contract_type=contract_type,
        visura_type=visura_type,
    )


def contratti(
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    return _prepare(
        "contratti_prepare",
        client_name=client_name,
        notes=notes,
        period=period,
        practice_type=practice_type,
        contract_type=contract_type,
        visura_type=visura_type,
    )


def durc(
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    return _prepare(
        "durc_prepare",
        client_name=client_name,
        notes=notes,
        period=period,
        practice_type=practice_type,
        contract_type=contract_type,
        visura_type=visura_type,
    )


def visure(
    client_name: str = "Cliente",
    notes: str = "",
    period: str = "",
    practice_type: str = "",
    contract_type: str = "",
    visura_type: str = "",
) -> dict:
    return _prepare(
        "visure_prepare",
        client_name=client_name,
        notes=notes,
        period=period,
        practice_type=practice_type,
        contract_type=contract_type,
        visura_type=visura_type,
    )
