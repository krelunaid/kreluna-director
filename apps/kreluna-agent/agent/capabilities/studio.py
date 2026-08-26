"""Bozze operative dei programmi dello studio, sempre senza azione definitiva."""

from __future__ import annotations

from kreluna_shared.crypto import sha256_hex
from kreluna_shared.workflows import (
    AccountingPrepareArgs,
    CameraPrepareArgs,
    ContractPrepareArgs,
    DurcPrepareArgs,
    VisurePrepareArgs,
    build_work_draft,
)

from agent.tools.render import render_card


def _result(capability: str, args) -> dict:
    draft = build_work_draft(capability, args)
    state = "BOZZA VALIDATA" if draft["ready_for_review"] else "DATI DA COMPLETARE"
    fields = [f"{item['label']}: {item['value']}" for item in draft["fields"]]
    image = render_card(
        f"{draft['role'].upper()} — {draft['title']}",
        [
            f"Stato: {state}",
            *fields,
            f"Programma: {draft['program']}",
            "",
            *[f"{index}. {step}" for index, step in enumerate(draft["steps"], start=1)],
            "",
            "SOLO BOZZA: nessun invio, firma, pagamento o download definitivo.",
        ],
    )
    return {
        "ok": True,
        "demo": False,
        "connected": False,
        "sent": False,
        "submitted": False,
        "downloaded": False,
        "payment_started": False,
        "spid_used": False,
        "smart_card_used": False,
        "client_name": draft["client_name"],
        "program": draft["program"],
        "draft": draft,
        "message": (
            f"{draft['title']} validata e pronta per il controllo umano. Nessuna operazione definitiva."
            if draft["ready_for_review"]
            else f"{draft['title']} aperta, ma mancano dati obbligatori. Nessuna operazione definitiva."
        ),
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {
                    "connected": False,
                    "role": draft["role"],
                    "program": draft["program"],
                    "ready_for_review": draft["ready_for_review"],
                    "sent": False,
                },
            }
        ],
    }


def contabilita(client_name: str = "Da indicare", notes: str = "", operation: str = "invoice_import", period: str = "", use_saved_access: bool = False) -> dict:
    return _result("contabilita_prepare", AccountingPrepareArgs(client_name=client_name, notes=notes, operation=operation, period=period, use_saved_access=use_saved_access))


def camera(client_name: str = "Da indicare", notes: str = "", practice_type: str = "", use_saved_access: bool = False) -> dict:
    return _result("camera_prepare", CameraPrepareArgs(client_name=client_name, notes=notes, practice_type=practice_type, use_saved_access=use_saved_access))


def contratti(client_name: str = "Da indicare", notes: str = "", contract_type: str = "", use_saved_access: bool = False) -> dict:
    return _result("contratti_prepare", ContractPrepareArgs(client_name=client_name, notes=notes, contract_type=contract_type, use_saved_access=use_saved_access))


def durc(client_name: str = "Da indicare", notes: str = "", request_type: str = "regularity_certificate", use_saved_access: bool = False) -> dict:
    return _result("durc_prepare", DurcPrepareArgs(client_name=client_name, notes=notes, request_type=request_type, use_saved_access=use_saved_access))


def visure(client_name: str = "Da indicare", notes: str = "", visura_type: str = "ordinary", use_saved_access: bool = False) -> dict:
    return _result("visure_prepare", VisurePrepareArgs(client_name=client_name, notes=notes, visura_type=visura_type, use_saved_access=use_saved_access))
