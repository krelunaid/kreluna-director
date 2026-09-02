"""Bozze operative condivise per i lavori dello studio.

L'IA può estrarre soltanto ciò che l'operatore ha scritto. Queste regole locali
trasformano i dati in una scheda verificabile e non espongono alcuna funzione di
invio, firma, pagamento, download definitivo o autenticazione forte.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

WORKFLOW_RULES_VERSION = "studio-2026-08-26"


class _BaseWorkArgs(BaseModel):
    client_name: str = Field(default="Da indicare", min_length=2, max_length=200)
    notes: str = Field(default="", max_length=500)
    use_saved_access: bool = False

    @field_validator("client_name", "notes")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())


class AccountingPrepareArgs(_BaseWorkArgs):
    operation: Literal["invoice_import", "ledger_import", "reconciliation", "other"] = "invoice_import"
    period: str = Field(default="", max_length=80)

    @field_validator("period")
    @classmethod
    def clean_period(cls, value: str) -> str:
        return " ".join(value.split())


class CameraPrepareArgs(_BaseWorkArgs):
    practice_type: str = Field(default="", max_length=120)

    @field_validator("practice_type")
    @classmethod
    def clean_practice(cls, value: str) -> str:
        return " ".join(value.split())


class ContractPrepareArgs(_BaseWorkArgs):
    contract_type: str = Field(default="", max_length=120)

    @field_validator("contract_type")
    @classmethod
    def clean_contract(cls, value: str) -> str:
        return " ".join(value.split())


class DurcPrepareArgs(_BaseWorkArgs):
    request_type: Literal["regularity_certificate"] = "regularity_certificate"


class VisurePrepareArgs(_BaseWorkArgs):
    visura_type: Literal["ordinary", "historical", "protests", "other"] = "ordinary"


WORKFLOW_SPECS: dict[str, dict] = {
    "contabilita_prepare": {
        "title": "Preparazione contabilità",
        "role": "pc-contabilita",
        "program": "AdE → IPSOA",
        "portals": ["ade", "ipsoa"],
        "detail_key": "operation",
        "detail_label": "Operazione",
        "detail_labels": {
            "invoice_import": "Scarico XML/P7M e importazione fatture",
            "ledger_import": "Importazione prima nota",
            "reconciliation": "Riconciliazione contabile",
            "other": "Attività contabile da verificare",
        },
        "steps": [
            "Apri il percorso configurato per il cliente",
            "Recupera da Fort Knox solo l'accesso ordinario autorizzato",
            "Prepara i file e l'importazione senza confermare operazioni definitive",
            "Ferma il lavoro per il controllo della persona",
        ],
    },
    "camera_prepare": {
        "title": "Preparazione pratica camerale",
        "role": "pc-camerali",
        "program": "CGN → ComUnica",
        "portals": ["cgn", "comunica"],
        "detail_key": "practice_type",
        "detail_label": "Tipo pratica",
        "steps": [
            "Apri CGN dal percorso configurato",
            "Recupera da Fort Knox l'accesso ordinario del cliente",
            "Prepara i dati della pratica e il passaggio a ComUnica",
            "Ferma il lavoro prima di firma o invio",
        ],
    },
    "contratti_prepare": {
        "title": "Preparazione contratto",
        "role": "pc-contratti",
        "program": "Agenzia delle Entrate",
        "portals": ["ade"],
        "detail_key": "contract_type",
        "detail_label": "Tipo contratto",
        "steps": [
            "Apri il percorso AdE configurato",
            "Recupera da Fort Knox l'accesso ordinario autorizzato",
            "Precompila la bozza con i soli dati forniti",
            "Ferma il lavoro prima di registrazione, firma o invio",
        ],
    },
    "durc_prepare": {
        "title": "Preparazione DURC",
        "role": "pc-durc",
        "program": "INPS",
        "portals": ["inps"],
        "detail_key": "request_type",
        "detail_label": "Richiesta",
        "detail_labels": {"regularity_certificate": "Certificato di regolarità contributiva"},
        "steps": [
            "Apri il percorso INPS configurato",
            "Ferma il lavoro davanti all'accesso SPID/CNS/CIE",
            "Dopo l'accesso umano prepara la richiesta e controlla l'anagrafica",
            "Ferma il lavoro prima dell'invio o del download definitivo",
        ],
    },
    "visure_prepare": {
        "title": "Preparazione visura",
        "role": "pc-visure",
        "program": "CGN",
        "portals": ["cgn"],
        "detail_key": "visura_type",
        "detail_label": "Tipo visura",
        "detail_labels": {
            "ordinary": "Ordinaria",
            "historical": "Storica",
            "protests": "Protesti",
            "other": "Da verificare",
        },
        "steps": [
            "Apri CGN dal percorso configurato",
            "Recupera da Fort Knox l'accesso ordinario del cliente",
            "Cerca il soggetto e prepara il tipo di visura richiesto",
            "Ferma il lavoro prima dell'acquisto o del download definitivo",
        ],
    },
}


def build_work_draft(capability: str, args: BaseModel | dict) -> dict:
    if capability not in WORKFLOW_SPECS:
        raise ValueError("workflow dello studio non supportato")
    raw = args.model_dump() if isinstance(args, BaseModel) else dict(args)
    spec = WORKFLOW_SPECS[capability]
    client = " ".join(str(raw.get("client_name") or "Da indicare").split())
    detail_key = str(spec["detail_key"])
    detail = " ".join(str(raw.get(detail_key) or "").split())
    detail_label = spec.get("detail_labels", {}).get(detail, detail)
    issues: list[str] = []
    if client.casefold() in {"da indicare", "cliente"}:
        issues.append("cliente mancante")
    if capability in {"camera_prepare", "contratti_prepare"} and not detail:
        issues.append(f"{str(spec['detail_label']).lower()} mancante")
    if capability == "visure_prepare" and detail == "other":
        issues.append("tipo visura da specificare")
    fields = [
        {"key": "client_name", "label": "Cliente", "value": client, "required": True, "source": "operatore"},
        {"key": detail_key, "label": spec["detail_label"], "value": detail_label or "Da indicare", "required": True, "source": "operatore"},
    ]
    if capability == "contabilita_prepare":
        fields.append({"key": "period", "label": "Periodo", "value": raw.get("period") or "Da verificare", "required": False, "source": "operatore"})
    return {
        "kind": "operational_draft",
        "rules_version": WORKFLOW_RULES_VERSION,
        "capability": capability,
        "title": spec["title"],
        "role": spec["role"],
        "client_name": client,
        "program": spec["program"],
        "fields": fields,
        "steps": list(spec["steps"]),
        "issues": issues,
        "ready_for_review": not issues,
        "credential_lookup": {
            "requested": bool(raw.get("use_saved_access")),
            "client_name": client,
            "portals": list(spec["portals"]),
            "source": "Fort Knox",
            "secret_exposed": False,
        },
        "sent": False,
        "submitted": False,
        "downloaded": False,
        "payment_started": False,
        "spid_used": False,
        "smart_card_used": False,
        "requires_human_approval": True,
    }


def build_invoice_draft(
    *,
    account_name: str,
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float,
    vat_note: str,
    vat_treatment: str = "standard",
    intent_lookup: str = "automatic",
    intent_received_date: str = "",
    intent_receipt_protocol: str = "",
    intent_protocol: str = "",
    intent_progressive: str = "",
    intent_year: str = "",
    lines: list[dict] | None = None,
) -> dict:
    """Uniforma anche la fattura alla stessa anteprima operativa locale."""

    detail_lines = lines or []
    if detail_lines:
        net = sum(
            (Decimal(str(line["quantity"])) * Decimal(str(line["unit_net_eur"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for line in detail_lines
        )
        vat = sum(
            (
                Decimal(str(line["quantity"]))
                * Decimal(str(line["unit_net_eur"]))
                * Decimal(str(line["vat_rate"]))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for line in detail_lines
        )
    else:
        net = Decimal(str(net_eur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vat = (net * Decimal(str(vat_rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = net + vat
    fields = [
        {"key": "account_name", "label": "Azienda emittente", "value": account_name or "Da verificare", "required": False, "source": "operatore"},
        {"key": "client_name", "label": "Destinatario", "value": client_name, "required": True, "source": "operatore"},
        {"key": "description", "label": "Prestazione", "value": description, "required": True, "source": "operatore"},
        {"key": "net_eur", "label": "Imponibile", "value": f"€ {net:.2f}", "required": True, "source": "operatore"},
        {"key": "vat", "label": "IVA", "value": vat_note or f"{vat_rate * 100:g}% · € {vat:.2f}", "required": True, "source": "operatore"},
    ]
    if detail_lines:
        fields = fields[:2]
        for index, line in enumerate(detail_lines, start=1):
            line_net = (Decimal(str(line["quantity"])) * Decimal(str(line["unit_net_eur"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            fields.append(
                {
                    "key": f"line_{index}",
                    "label": f"Riga {index}",
                    "value": (
                        f"{line['description']} · q.tà {line['quantity']:g} · € {line_net:.2f} · "
                        + (
                            "N3.5 · dichiarazione d'intento"
                            if line.get("vat_treatment") == "intent_declaration"
                            else f"IVA {float(line['vat_rate']) * 100:g}%"
                        )
                    ),
                    "required": True,
                    "source": "operatore",
                }
            )
        fields.extend(
            [
                {"key": "net_eur", "label": "Imponibile", "value": f"€ {net:.2f}", "required": True, "source": "calcolo locale"},
                {"key": "vat", "label": "IVA", "value": vat_note or f"€ {vat:.2f}", "required": True, "source": "calcolo per riga"},
            ]
        )
    if vat_treatment == "intent_declaration":
        if intent_lookup == "automatic":
            fields.append(
                {
                    "key": "intent_lookup",
                    "label": "Dichiarazione d'intento",
                    "value": "Ricerca automatica nell'anagrafica Webdesk",
                    "required": True,
                    "source": "PC-FATTURE",
                }
            )
        elif intent_received_date and intent_receipt_protocol:
            fields.extend(
                [
                    {"key": "intent_received_date", "label": "Data ricevuta telematica", "value": intent_received_date, "required": True, "source": "operatore"},
                    {"key": "intent_receipt_protocol", "label": "Protocollo ricezione DI", "value": intent_receipt_protocol, "required": True, "source": "operatore"},
                ]
            )
        else:
            fields.extend(
                [
                    {"key": "intent_protocol", "label": "Protocollo dichiarazione", "value": intent_protocol, "required": True, "source": "operatore"},
                    {"key": "intent_progressive", "label": "Progressivo", "value": intent_progressive, "required": True, "source": "operatore"},
                    {"key": "intent_year", "label": "Anno dichiarazione", "value": intent_year, "required": True, "source": "operatore"},
                ]
            )
    fields.append({"key": "total", "label": "Totale", "value": f"€ {total:.2f}", "required": True, "source": "calcolo locale"})
    return {
        "kind": "operational_draft",
        "rules_version": WORKFLOW_RULES_VERSION,
        "capability": "invoice_prepare_demo",
        "title": "Preparazione fattura elettronica",
        "role": "pc-fatture",
        "client_name": client_name,
        "program": "Webdesk / Agenzia delle Entrate",
        "fields": fields,
        "customer_workflow": {
            "search_first": True,
            "search_by": ["Codice", "Denominazione", "Codice fiscale"],
            "result_action": "Accedi",
            "create_only_if_missing": True,
            "create_path": ["Clienti", "Crea nuovo"],
            "required_create_fields": [
                "Tipologia cliente",
                "Codice fiscale o Partita IVA",
                "Denominazione oppure nome e cognome",
                "Indirizzo della sede",
                "Codice destinatario SDI",
            ],
            "stop_before": "Salva cliente",
        },
        "intent_declaration_workflow": {
            "lookup": intent_lookup,
            "customer_path": ["Home", "Clienti", "Apri cliente", "Dichiarazione d'intento"],
            "webdesk_fields": ["Data ricevuta telematica", "Protocollo di ricezione della DI"],
            "missing_signal": "Nessuna dichiarazione presente",
            "missing_action": "Fermati e chiedi i dati; non inventare e non salvare l'anagrafica",
            "invoice_vat": "Art. 8 c.1 lett.c DPR 633/72 - N3.5",
            "invoice_row_action": "Attiva DI soltanto sulle righe N3.5",
        },
        "steps": [
            "Apri IPSOA, entra in Webdesk e scegli Servizi SMART",
            "Usa Fort Knox soltanto per l'accesso ordinario autorizzato",
            "Cerca il cliente per codice, denominazione o codice fiscale",
            "Se il cliente esiste, verifica codice fiscale e Partita IVA e premi Accedi",
            "Se non esiste, apri Clienti > Crea nuovo e compila i dati anagrafici",
            "Ferma il lavoro prima di salvare un nuovo cliente e chiedi conferma",
            "Torna a Home > Fatture > Crea nuovo e precompila la fattura",
            "Per le righe N3.5 leggi prima la dichiarazione nell'anagrafica del destinatario",
            "Se Webdesk mostra Nessuna dichiarazione presente, fermati e chiedi i dati",
            "Applica Art. 8 c.1 lett.c DPR 633/72 - N3.5 e DI soltanto alle righe interessate",
            "Ferma il lavoro prima di Salva, Emetti o Invia",
        ],
        "issues": [],
        "ready_for_review": True,
        "credential_lookup": {
            "requested": False,
            "client_name": account_name or client_name,
            "portals": ["webdesk", "ade"],
            "source": "Fort Knox",
            "secret_exposed": False,
        },
        "sent": False,
        "submitted": False,
        "downloaded": False,
        "payment_started": False,
        "spid_used": False,
        "smart_card_used": False,
        "requires_human_approval": True,
    }
