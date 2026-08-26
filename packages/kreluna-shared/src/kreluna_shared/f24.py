"""Regole strutturali F24 condivise da Director e Agent.

Il modello IA può estrarre i dati pronunciati dall'operatore, ma non decide se
un tributo è dovuto. Questo modulo valida forma, compatibilità e totali in modo
deterministico e non contiene alcuna funzione di invio o pagamento.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

F24_RULES_VERSION = "ade-2026-03-26"
F24_RULES_SOURCE = "https://www1.agenziaentrate.gov.it/servizi/codici/ricerca/"

F24FormType = Literal["ordinary", "simplified", "elide", "accise", "public_entities"]
F24Section = Literal[
    "erario",
    "inps",
    "regioni",
    "imu_locali",
    "inail",
    "altri_enti",
    "elide",
    "accise",
    "public_entities",
]

FORM_LABELS: dict[str, str] = {
    "ordinary": "F24 ordinario",
    "simplified": "F24 semplificato",
    "elide": "F24 ELIDE",
    "accise": "F24 Accise",
    "public_entities": "F24 Enti pubblici",
}

SECTION_LABELS: dict[str, str] = {
    "erario": "Erario",
    "inps": "INPS",
    "regioni": "Regioni",
    "imu_locali": "IMU e tributi locali",
    "inail": "INAIL",
    "altri_enti": "Altri enti",
    "elide": "Elementi identificativi",
    "accise": "Accise/Monopoli",
    "public_entities": "Enti pubblici",
}

ALLOWED_SECTIONS: dict[str, frozenset[str]] = {
    "ordinary": frozenset({"erario", "inps", "regioni", "imu_locali", "inail", "altri_enti"}),
    "simplified": frozenset({"erario", "regioni", "imu_locali"}),
    "elide": frozenset({"elide"}),
    "accise": frozenset({"accise"}),
    "public_entities": frozenset({"public_entities"}),
}

# Solo voci verificate nella ricerca guidata ufficiale AdE. Il catalogo è
# deliberatamente piccolo: una voce assente deve essere indicata dall'operatore
# e non viene mai completata usando la memoria del modello.
OFFICIAL_RULES: dict[str, dict[str, str]] = {
    **{
        f"iva_monthly_{month:02d}": {
            "tax_code": f"60{month:02d}",
            "section": "erario",
            "month": f"{month:02d}",
            "label": f"IVA mensile mese {month:02d}",
        }
        for month in range(1, 13)
    },
    **{
        f"iva_quarterly_{quarter}": {
            "tax_code": f"603{quarter}",
            "section": "erario",
            "month": "",
            "label": f"IVA trimestrale trimestre {quarter}",
        }
        for quarter in range(1, 5)
    },
    "iva_monthly_advance": {
        "tax_code": "6013",
        "section": "erario",
        "month": "",
        "label": "Acconto IVA mensile",
    },
    "iva_quarterly_advance": {
        "tax_code": "6035",
        "section": "erario",
        "month": "",
        "label": "Acconto IVA trimestrale",
    },
    "withholding_salary": {
        "tax_code": "1001",
        "section": "erario",
        "month": "",
        "label": "Ritenute su retribuzioni",
    },
    "withholding_self_employed": {
        "tax_code": "1040",
        "section": "erario",
        "month": "",
        "label": "Ritenute su lavoro autonomo",
    },
}


def official_rule_catalog() -> str:
    return "\n".join(f"- {key}: {value['label']}" for key, value in OFFICIAL_RULES.items())


class F24Line(BaseModel):
    section: F24Section
    tax_code: str = Field(default="", max_length=4, pattern=r"^(?:[A-Za-z0-9]{4})?$")
    rule_key: str = Field(default="", max_length=40, pattern=r"^[a-z0-9_]*$")
    reference_year: str = Field(pattern=r"^(?:19|20|21)\d{2}$")
    debit_eur: float = Field(default=0, ge=0, le=100_000_000)
    credit_eur: float = Field(default=0, ge=0, le=100_000_000)
    installment: str = Field(default="", max_length=8)
    month: str = Field(default="", pattern=r"^(?:0[1-9]|1[0-2])?$")
    province: str = Field(default="", pattern=r"^(?:[A-Za-z]{2})?$")
    entity_code: str = Field(default="", max_length=8, pattern=r"^[A-Za-z0-9]*$")
    type_code: str = Field(default="", max_length=4, pattern=r"^[A-Za-z0-9]*$")
    identifying_elements: str = Field(default="", max_length=17, pattern=r"^[A-Za-z0-9]*$")
    office_code: str = Field(default="", max_length=5, pattern=r"^[A-Za-z0-9]*$")
    act_code: str = Field(default="", max_length=11, pattern=r"^[A-Za-z0-9]*$")
    reference_code: str = Field(default="", max_length=18, pattern=r"^[A-Za-z0-9]*$")

    @model_validator(mode="before")
    @classmethod
    def resolve_official_rule(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        raw = dict(value)
        key = str(raw.get("rule_key") or "").strip().lower()
        if not key:
            return raw
        rule = OFFICIAL_RULES.get(key)
        if rule is None:
            raise ValueError("regola F24 non presente nel catalogo ufficiale locale")
        supplied_code = str(raw.get("tax_code") or "").strip().upper()
        supplied_section = str(raw.get("section") or "").strip().lower()
        if supplied_code and supplied_code != rule["tax_code"]:
            raise ValueError("codice tributo in conflitto con la regola ufficiale")
        if supplied_section and supplied_section != rule["section"]:
            raise ValueError("sezione in conflitto con la regola ufficiale")
        raw["tax_code"] = rule["tax_code"]
        raw["section"] = rule["section"]
        if rule["month"] and not raw.get("month"):
            raw["month"] = rule["month"]
        return raw

    @field_validator(
        "tax_code",
        "province",
        "entity_code",
        "type_code",
        "identifying_elements",
        "office_code",
        "act_code",
        "reference_code",
    )
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("installment")
    @classmethod
    def valid_installment(cls, value: str) -> str:
        clean = value.strip().replace("/", "")
        if clean and (not clean.isdigit() or len(clean) not in {2, 4, 6}):
            raise ValueError("rateazione non valida")
        return clean

    @model_validator(mode="after")
    def one_amount_side(self) -> F24Line:
        if not self.tax_code:
            raise ValueError("codice tributo mancante")
        debit = Decimal(str(self.debit_eur))
        credit = Decimal(str(self.credit_eur))
        if debit <= 0 and credit <= 0:
            raise ValueError("ogni riga richiede un importo a debito o a credito")
        if debit > 0 and credit > 0:
            raise ValueError("una riga non può avere insieme debito e credito")
        if self.section == "elide" and credit > 0:
            raise ValueError("F24 ELIDE non ammette importi a credito")
        if self.section == "accise" and (not self.entity_code or not self.province):
            raise ValueError("la sezione Accise richiede ente e provincia")
        return self


class F24PrepareArgs(BaseModel):
    client_name: str = Field(default="Da indicare", min_length=2, max_length=200)
    taxpayer_id: str = Field(default="", max_length=16, pattern=r"^[A-Za-z0-9]*$")
    form_type: F24FormType = "ordinary"
    payment_date: str = Field(default="", pattern=r"^(?:\d{4}-\d{2}-\d{2})?$")
    lines: list[F24Line] = Field(default_factory=list, max_length=30)
    period: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=500)
    use_saved_access: bool = False

    @field_validator("client_name", "period", "note")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("taxpayer_id")
    @classmethod
    def uppercase_taxpayer(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def compatible_sections(self) -> F24PrepareArgs:
        allowed = ALLOWED_SECTIONS[self.form_type]
        wrong = sorted({line.section for line in self.lines if line.section not in allowed})
        if wrong:
            raise ValueError(
                f"sezioni non compatibili con {FORM_LABELS[self.form_type]}: {', '.join(wrong)}"
            )
        return self


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_f24_draft(args: F24PrepareArgs | dict) -> dict:
    """Build a review-only draft. Empty lines create a worksheet, never a valid F24."""

    parsed = args if isinstance(args, F24PrepareArgs) else F24PrepareArgs.model_validate(args)
    debit = _money(sum((Decimal(str(line.debit_eur)) for line in parsed.lines), Decimal(0)))
    credit = _money(sum((Decimal(str(line.credit_eur)) for line in parsed.lines), Decimal(0)))
    balance = _money(debit - credit)
    issues: list[str] = []
    if parsed.client_name == "Da indicare":
        issues.append("cliente mancante")
    if not parsed.lines:
        issues.append("righe tributo mancanti")
    if balance < 0:
        issues.append("crediti superiori ai debiti: verifica la compensazione")
    ready = not issues
    return {
        "kind": "f24_draft",
        "rules_version": F24_RULES_VERSION,
        "rules_source": F24_RULES_SOURCE,
        "form_type": parsed.form_type,
        "form_label": FORM_LABELS[parsed.form_type],
        "client_name": parsed.client_name,
        "taxpayer_id": parsed.taxpayer_id,
        "payment_date": parsed.payment_date,
        "period": parsed.period,
        "lines": [
            {
                **line.model_dump(),
                "section_label": SECTION_LABELS[line.section],
            }
            for line in parsed.lines
        ],
        "totals": {
            "debit_eur": float(debit),
            "credit_eur": float(credit),
            "balance_eur": float(balance),
        },
        "issues": issues,
        "ready_for_review": ready,
        "sent": False,
        "payment_started": False,
        "requires_human_approval": True,
    }
