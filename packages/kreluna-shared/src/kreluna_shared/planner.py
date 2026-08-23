from __future__ import annotations

import json
import re
from typing import Any

from kreluna_shared.capabilities import CAPABILITIES, DENIED_CAPABILITIES, validate_capability_args
from kreluna_shared.models import PlannedTask, PlanResult, PolicyDecision, Risk
from kreluna_shared.policy import PolicyEngine

INJECTION_MARKERS = (
    "ignore previous",
    "ignora le istruzioni",
    "disattiva sicurezz",
    "disable security",
    "export credential",
    "esporta credenzial",
    "remote shell",
    "powershell -enc",
    "cmd.exe /c",
)

DENY_PHRASES = (
    "disattiva la sicurezza",
    "disattiva sicurezza",
    "spegni windows",
    "cancella tutti i file",
    "esporta le password",
    "dammi le credenziali",
    "apri una shell remota",
)


def _parse_amount(raw: str) -> float:
    raw = raw.strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", raw):
        return float(raw.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        return float(raw.replace(".", ""))
    if "," in raw and "." not in raw:
        return float(raw.replace(",", "."))
    return float(raw)


def _money(text: str) -> float | None:
    match = re.search(
        r"(?:eur(?:o)?|€)\s*([0-9]{1,7}(?:[.,][0-9]{3})?(?:[.,][0-9]{1,2})?)|([0-9]{1,7}(?:[.,][0-9]{3})?(?:[.,][0-9]{1,2})?)\s*(?:eur(?:o)?|€)",
        text,
        flags=re.I,
    )
    if not match:
        return None
    return _parse_amount(match.group(1) or match.group(2))


def _client_name(text: str) -> str | None:
    patterns = [
        r"fattura(?:\s+demo)?\s+a(?:l\s+cliente)?\s+([A-Za-zÀ-ÿ' ]{3,60}?)(?:\s+per|\s*,|\s+di|\s+euro|\s+eur|\s+€|$)",
        r"(?:cliente|a)\s+([A-Za-zÀ-ÿ']+\s+[A-Za-zÀ-ÿ']+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return " ".join(match.group(1).split()).title()
    return None


def _description(text: str) -> str:
    match = re.search(r"per\s+([^,.]{3,80})", text, flags=re.I)
    if match:
        desc = match.group(1)
        desc = re.split(r"\s+(?:eur|euro|€)\b", desc, flags=re.I)[0]
        return desc.strip().capitalize()
    return "Consulenza"


def plan_deterministic(text: str) -> PlanResult:
    raw = text.strip()
    lowered = raw.lower()

    if any(phrase in lowered for phrase in DENY_PHRASES) or any(m in lowered for m in INJECTION_MARKERS):
        return PlanResult(
            ok=False,
            summary="Richiesta bloccata dalla policy di sicurezza.",
            denied=True,
            deny_reason="Il comando chiede un'azione vietata o tenta di aggirare le regole.",
            source="deterministic",
        )

    if "ferma tutto" in lowered or lowered.strip() in {"stop", "kill", "basta"}:
        return PlanResult(
            ok=True,
            summary="Kill switch: fermo tutti gli agenti e i task in corso.",
            tasks=[],
            source="deterministic-kill",
        )

    notepad = re.search(
        r"(?:apri\s+)?(?:il\s+)?blocco\s+note.*?(?:scrivi|testo)\s*:?\s*[\"']?(.+?)[\"']?$",
        raw,
        flags=re.I | re.S,
    )
    if notepad or ("blocco note" in lowered and "scrivi" in lowered):
        written = notepad.group(1).strip() if notepad else raw
        written = written.strip(" .\"'")
        if "scrivi" in lowered:
            after = re.split(r"scrivi\s*:?\s*", raw, flags=re.I, maxsplit=1)
            if len(after) == 2:
                written = after[1].strip().strip(" .\"'")
        return PlanResult(
            ok=True,
            summary=f"Apro il blocco note controllato e scrivo: {written}",
            tasks=[
                PlannedTask(
                    goal=f"Scrivere nel blocco note: {written}",
                    capability="notepad_write",
                    args={"text": written},
                    risk=Risk.LOW,
                    needs_approval=False,
                )
            ],
        )

    if "fattura" in lowered:
        client = _client_name(lowered) or "Mario Rossi"
        net = _money(lowered) or 1500.0
        description = _description(raw)
        return PlanResult(
            ok=True,
            summary=f"Preparo una fattura DEMO per {client}: {description}, € {net:,.2f} + IVA.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare fattura demo a {client} per {description}",
                    capability="invoice_prepare_demo",
                    args={
                        "client_name": client,
                        "description": description,
                        "net_eur": net,
                        "vat_rate": 0.22,
                    },
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if "document" in lowered or "documenti mancanti" in lowered:
        return PlanResult(
            ok=True,
            summary="Controllo in sola lettura i documenti mancanti nello studio demo.",
            tasks=[
                PlannedTask(
                    goal="Verificare documenti mancanti",
                    capability="document_check",
                    args={"scope": "missing_documents"},
                    risk=Risk.LOW,
                    needs_approval=False,
                )
            ],
        )

    if "email" in lowered or "posta" in lowered:
        if any(word in lowered for word in ("invia", "inviala", "manda", "spedisci")):
            return PlanResult(
                ok=False,
                summary="Non invio email o PEC in questa versione.",
                denied=True,
                deny_reason="L'invio email/PEC richiede Approval Gateway e non è abilitato nel prototipo.",
            )
        return PlanResult(
            ok=True,
            summary="Preparo una bozza email, senza inviarla.",
            tasks=[
                PlannedTask(
                    goal="Preparare bozza email",
                    capability="email_draft",
                    args={
                        "subject": "Aggiornamento studio",
                        "body": raw,
                    },
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(word in lowered for word in ("f24", "pagamento", "bonifico", "pec")):
        return PlanResult(
            ok=False,
            summary="Operazione fiscale/irreversibile non abilitata in questo prototipo.",
            denied=True,
            deny_reason="F24, pagamenti e PEC reali sono esclusi finché non esiste l'Approval Gateway di produzione.",
        )

    return PlanResult(
        ok=False,
        summary="Non ho capito un obiettivo eseguibile. Prova con un comando dello studio.",
        denied=False,
        deny_reason="Nessuna capability riconosciuta. Esempi: apri blocco note e scrivi CIAO; prepara fattura demo a Rossi per consulenza EUR 1500.",
    )


def apply_policy(plan: PlanResult, engine: PolicyEngine, license_state: str) -> PlanResult:
    if plan.denied or not plan.ok:
        return plan
    safe_tasks: list[PlannedTask] = []
    for task in plan.tasks:
        if task.capability in DENIED_CAPABILITIES:
            return PlanResult(
                ok=False,
                summary="Capability vietata.",
                denied=True,
                deny_reason=f"{task.capability} è nella deny list.",
                source=plan.source,
            )
        if task.capability not in CAPABILITIES:
            return PlanResult(
                ok=False,
                summary="Capability sconosciuta: rifiuto.",
                denied=True,
                deny_reason=f"Capability non in allowlist: {task.capability}",
                source=plan.source,
            )
        try:
            args = validate_capability_args(task.capability, task.args)
        except Exception as exc:
            return PlanResult(
                ok=False,
                summary="Argomenti non validi.",
                denied=True,
                deny_reason=str(exc),
                source=plan.source,
            )
        decision = engine.decide(task.capability, license_state)
        if decision.decision is PolicyDecision.DENY:
            return PlanResult(
                ok=False,
                summary=decision.reason,
                denied=True,
                deny_reason=decision.reason,
                source=plan.source,
            )
        if decision.decision is PolicyDecision.DENY_LICENSE:
            return PlanResult(
                ok=False,
                summary=decision.reason,
                denied=True,
                deny_reason=decision.reason,
                source=plan.source,
            )
        task.args = args
        task.risk = decision.risk
        task.needs_approval = decision.decision is PolicyDecision.APPROVAL
        safe_tasks.append(task)
    return plan.model_copy(update={"tasks": safe_tasks})


def parse_llm_plan(payload: Any) -> PlanResult:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return PlanResult.model_validate(payload)
