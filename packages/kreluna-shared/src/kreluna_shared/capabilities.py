from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class NotepadWriteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class InvoicePrepareArgs(BaseModel):
    client_name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=500)
    net_eur: float = Field(gt=0, le=1_000_000)
    vat_rate: float = Field(default=0.22, ge=0, le=1)

    @field_validator("client_name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return " ".join(value.split())


class InvoiceSubmitArgs(BaseModel):
    draft_id: str = Field(min_length=1, max_length=80)


class F24PrepareArgs(BaseModel):
    period: str = Field(default="in_scadenza", max_length=80)
    note: str = Field(default="", max_length=500)


class DocumentCheckArgs(BaseModel):
    scope: str = Field(default="missing_documents", max_length=80)


class EmailDraftArgs(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    to: str | None = None


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
        description="Prepara una fattura nello gestionale DEMO locale. Non invia nulla.",
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
        description="Prepara F24 in bozza. Non invia e non paga. Programma da collegare.",
        demo_only=True,
    ),
    "document_check": CapabilitySpec(
        name="document_check",
        args_model=DocumentCheckArgs,
        default_risk="low",
        description="Controllo in sola lettura dei documenti mancanti demo.",
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
