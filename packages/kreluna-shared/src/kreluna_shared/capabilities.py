from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from kreluna_shared.f24 import F24PrepareArgs
from kreluna_shared.workflows import (
    AccountingPrepareArgs,
    CameraPrepareArgs,
    ContractPrepareArgs,
    DurcPrepareArgs,
    VisurePrepareArgs,
)


class NotepadWriteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class InvoiceLineArgs(BaseModel):
    description: str = Field(min_length=2, max_length=500)
    quantity: float = Field(default=1, gt=0, le=100_000)
    unit_net_eur: float = Field(gt=0, le=1_000_000)
    vat_rate: float = Field(default=0.22, ge=0, le=1)
    vat_treatment: Literal["standard", "intent_declaration"] = "standard"

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def normalize_vat(self) -> InvoiceLineArgs:
        if self.vat_treatment == "intent_declaration":
            self.vat_rate = 0
        return self


class InvoicePrepareArgs(BaseModel):
    account_name: str | None = Field(default=None, min_length=2, max_length=200)
    client_name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=500)
    net_eur: float = Field(gt=0, le=1_000_000)
    vat_rate: float = Field(default=0.22, ge=0, le=1)
    vat_note: str = Field(default="", max_length=300)
    vat_treatment: Literal["standard", "intent_declaration"] = "standard"
    intent_lookup: Literal["automatic", "manual"] = "automatic"
    intent_received_date: str = Field(default="", pattern=r"^(?:\d{2}/\d{2}/\d{4})?$")
    intent_receipt_protocol: str = Field(default="", max_length=60)
    intent_protocol: str = Field(default="", pattern=r"^(?:\d{17})?$")
    intent_progressive: str = Field(default="", pattern=r"^(?:\d{6})?$")
    intent_year: str = Field(default="", pattern=r"^(?:\d{4})?$")
    lines: list[InvoiceLineArgs] = Field(default_factory=list, max_length=100)

    @field_validator("account_name", "client_name", "description", "vat_note")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())

    @model_validator(mode="before")
    @classmethod
    def normalize_intent_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        cleaned = dict(value)
        vat_note = str(cleaned.get("vat_note") or "").lower()
        if "dichiarazione" in vat_note and "intento" in vat_note:
            cleaned["vat_treatment"] = "intent_declaration"
        # I vecchi task non avevano questi campi: stringhe vuote restano valide
        # per il trattamento IVA ordinario.
        for key in (
            "intent_received_date",
            "intent_receipt_protocol",
            "intent_protocol",
            "intent_progressive",
            "intent_year",
        ):
            cleaned[key] = str(cleaned.get(key) or "").strip()
        return cleaned

    @model_validator(mode="after")
    def validate_intent_declaration(self) -> InvoicePrepareArgs:
        intent_lines = [line for line in self.lines if line.vat_treatment == "intent_declaration"]
        if self.vat_treatment == "intent_declaration" and self.lines and not intent_lines:
            # Le vecchie richieste indicavano la DI soltanto a livello di fattura.
            for line in self.lines:
                line.vat_treatment = "intent_declaration"
                line.vat_rate = 0
            intent_lines = list(self.lines)
        if self.vat_treatment != "intent_declaration" and not intent_lines:
            return self
        self.vat_treatment = "intent_declaration"
        if not self.lines or len(intent_lines) == len(self.lines):
            self.vat_rate = 0
        if self.intent_lookup == "automatic":
            self.vat_note = "N3.5 · Dichiarazione d'intento · ricerca automatica in Webdesk"
        elif self.intent_received_date and self.intent_receipt_protocol:
            self.vat_note = (
                "N3.5 · Dichiarazione d'intento · "
                f"ricevuta il {self.intent_received_date} · protocollo {self.intent_receipt_protocol}"
            )
        elif self.intent_protocol and self.intent_progressive and self.intent_year:
            # Compatibilita con le bozze create prima della mappatura reale di Webdesk.
            self.vat_note = (
                "N3.5 · Dichiarazione d'intento · "
                f"protocollo {self.intent_protocol}-{self.intent_progressive} · anno {self.intent_year}"
            )
        else:
            raise ValueError(
                "La dichiarazione manuale richiede data ricevuta e protocollo Webdesk"
            )
        return self


class InvoiceSubmitArgs(BaseModel):
    draft_id: str = Field(min_length=1, max_length=80)


class DocumentCheckArgs(BaseModel):
    scope: str = Field(default="missing_documents", max_length=80)


class PaymentPrepareArgs(BaseModel):
    beneficiary: str = Field(default="da definire", max_length=200)
    reason: str = Field(default="pagamento", max_length=500)
    amount_eur: float = Field(default=0, ge=0, le=1_000_000)


class InvoiceCheckArgs(BaseModel):
    scope: str = Field(default="fatture_da_controllare", max_length=80)


class EmailDraftArgs(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    to: str | None = None


class PortalOpenArgs(BaseModel):
    portal: str = Field(min_length=2, max_length=60)
    query: str = Field(default="", max_length=200)
    use_saved_access: bool = False
    invoice: InvoicePrepareArgs | None = None

    @field_validator("portal")
    @classmethod
    def known_shape(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not all(ch.isalnum() or ch in "-_" for ch in cleaned):
            raise ValueError("portale non valido")
        return cleaned

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return " ".join(value.split())


class CapabilitySpec(BaseModel):
    name: str
    args_model: type[BaseModel]
    default_risk: str
    description: str
    operational: bool = True
    irreversible: bool = False
    demo_only: bool = False


CAPABILITIES: dict[str, CapabilitySpec] = {
    "notepad_write": CapabilitySpec(
        name="notepad_write",
        args_model=NotepadWriteArgs,
        default_risk="low",
        description="Apre un blocco note controllato e scrive testo. Nessun salvataggio file.",
    ),
    "invoice_prepare_demo": CapabilitySpec(
        name="invoice_prepare_demo",
        args_model=InvoicePrepareArgs,
        default_risk="medium",
        description=(
            "Prepara una fattura sul PC (in produzione: Webdesk / sito Agenzia delle Entrate, "
            "utenza cliente smart card / SPID). In demo usa una finestra locale. Non invia."
        ),
        demo_only=True,
    ),
    "invoice_submit_demo": CapabilitySpec(
        name="invoice_submit_demo",
        args_model=InvoiceSubmitArgs,
        default_risk="high",
        description="Cambia lo stato DEMO da BOZZA a EMESSA. Mai un portale fiscale reale.",
        irreversible=True,
        demo_only=True,
    ),
    "f24_prepare": CapabilitySpec(
        name="f24_prepare",
        args_model=F24PrepareArgs,
        default_risk="medium",
        description=(
            "Prepara e valida una bozza strutturata F24 ordinario, semplificato, ELIDE, "
            "Accise o Enti pubblici. Non trasmette e non paga."
        ),
        demo_only=False,
    ),
    "contabilita_prepare": CapabilitySpec(
        name="contabilita_prepare",
        args_model=AccountingPrepareArgs,
        default_risk="medium",
        description="Prepara lo scarico AdE XML/P7M, il carico IPSOA e l'importatore contabile. Nessun SPID.",
        demo_only=False,
    ),
    "camera_prepare": CapabilitySpec(
        name="camera_prepare",
        args_model=CameraPrepareArgs,
        default_risk="medium",
        description="Prepara una pratica camerale su sito CGN e Desktop ComUnica. Nessun invio.",
        demo_only=False,
    ),
    "contratti_prepare": CapabilitySpec(
        name="contratti_prepare",
        args_model=ContractPrepareArgs,
        default_risk="medium",
        description="Prepara un contratto sul sito AdE (utenza Samuele). Nessun invio.",
        demo_only=False,
    ),
    "durc_prepare": CapabilitySpec(
        name="durc_prepare",
        args_model=DurcPrepareArgs,
        default_risk="medium",
        description="Prepara una richiesta DURC sul sito INPS. Nessun SPID, nessun invio.",
        demo_only=False,
    ),
    "visure_prepare": CapabilitySpec(
        name="visure_prepare",
        args_model=VisurePrepareArgs,
        default_risk="medium",
        description="Prepara una visura sul sito CGN. Nessun download reale.",
        demo_only=False,
    ),
    "portal_open": CapabilitySpec(
        name="portal_open",
        args_model=PortalOpenArgs,
        default_risk="medium",
        description=(
            "Apre davvero il portale nel browser del PC, aspetta il login umano e compila "
            "il campo di ricerca. Non preme invio, non scarica, non invia."
        ),
        demo_only=False,
    ),
    "portal_learn": CapabilitySpec(
        name="portal_learn",
        args_model=PortalOpenArgs,
        default_risk="low",
        description=(
            "Guarda la pagina del portale aperta sul PC e scrive i nomi dei campi, "
            "per imparare il programma. Non scrive, non clicca, non invia."
        ),
        demo_only=False,
    ),
    "document_check": CapabilitySpec(
        name="document_check",
        args_model=DocumentCheckArgs,
        default_risk="low",
        description="Controllo in sola lettura dei documenti mancanti demo.",
        operational=True,
    ),
    "payment_prepare": CapabilitySpec(
        name="payment_prepare",
        args_model=PaymentPrepareArgs,
        default_risk="medium",
        description="Prepara un pagamento in bozza. Non esegue bonifici.",
        demo_only=True,
    ),
    "invoice_check": CapabilitySpec(
        name="invoice_check",
        args_model=InvoiceCheckArgs,
        default_risk="low",
        description="Controlla fatture in sola lettura. Non modifica e non invia.",
        operational=True,
    ),
    "email_draft": CapabilitySpec(
        name="email_draft",
        args_model=EmailDraftArgs,
        default_risk="medium",
        description="Prepara una bozza email. Non invia.",
    ),
}

DENIED_CAPABILITIES = frozenset(
    {
        "credential_export",
        "disable_security",
        "arbitrary_remote_shell",
        "bulk_delete_without_recovery_plan",
        "remote_shell",
        "eval_code",
    }
)

APPROVAL_CAPABILITIES = frozenset(
    {
        "invoice_submit",
        "invoice_submit_demo",
        "f24_submit",
        "payment",
        "pec_send",
        "email_send",
        "destructive_delete",
    }
)


def validate_capability_args(capability: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise ValueError(f"UNKNOWN_CAPABILITY:{capability}")
    parsed = spec.args_model.model_validate(args)
    return parsed.model_dump()
