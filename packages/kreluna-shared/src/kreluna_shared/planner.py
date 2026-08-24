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
    raw = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", raw):
        return float(raw.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        return float(raw.replace(".", ""))
    if "," in raw and "." not in raw:
        return float(raw.replace(",", "."))
    return float(raw.replace(".", "").replace(",", ".")) if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw) else float(raw)


def _money(text: str) -> float | None:
    range_mila = re.search(
        r"(\d{1,3})\s*[-–/]\s*(\d{1,3})\s*(?:mila|thousand|k)\b",
        text,
        flags=re.I,
    )
    if range_mila:
        low, high = int(range_mila.group(1)), int(range_mila.group(2))
        return round((low + high) / 2 * 1000, 2)

    range_plain = re.search(
        r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*[-–/]\s*(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})",
        text,
    )
    if range_plain:
        low = _parse_amount(range_plain.group(1).replace(" ", ""))
        high = _parse_amount(range_plain.group(2).replace(" ", ""))
        return round((low + high) / 2, 2)

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
        r"(?:fattura|invoice)(?:\s+demo)?\s+(?:ad|al cliente|a|to)\s+([A-Za-zÀ-ÿ']+(?:\s+[A-Za-zÀ-ÿ']+){0,3}?)(?=\s+(?:per|di|for|da|euro|eur|€|\d)|[,.]|$)",
        r"(?:cliente)\s+([A-Za-zÀ-ÿ']+\s+[A-Za-zÀ-ÿ']+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            name = " ".join(match.group(1).split()).title()
            if name.lower() in {"demo", "una", "la", "the"}:
                continue
            return name
    return None


def _looks_like_email(text: str) -> bool:
    return bool(re.search(r"\b(?:e-?mail|mail|posta|pec)\b", text, flags=re.I))


def _wants_real_email_send(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"\bpec\b", lowered) and re.search(r"\b(?:invia|inviala|spedisci)\b", lowered):
        return True
    return bool(re.search(r"invia(?:la)?\s+(?:davvero|per\s+davvero)", lowered))


def _email_to(text: str) -> str | None:
    addr = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    if addr:
        return addr.group(0)
    match = re.search(
        r"\b(?:a|ad|to)\s+([A-Za-zÀ-ÿ0-9._+\-]+(?:\s+[A-Za-zÀ-ÿ']+){0,3})"
        r"(?=\s+(?:dicendo|che|per|con|,|$))",
        text,
        flags=re.I,
    )
    if not match:
        return None
    name = " ".join(match.group(1).split())
    if name.lower() in {"me", "mi", "me stesso", "una", "la"}:
        return None
    if "@" not in name and " " in name:
        return name.title()
    return name


def _email_body(text: str) -> str:
    match = re.search(r"(?:dicendo|che dice|con testo|testo)\s*:?\s*(.+)$", text, flags=re.I | re.S)
    if match:
        body = match.group(1).strip().strip(" .\"'")
        if body:
            return body
    return text.strip()


def _description(text: str) -> str:
    lowered = text.lower()
    if "manodopera" in lowered or "manpower" in lowered:
        return "Manodopera"
    match = re.search(r"(?:per|for|di)\s+([^,.]{3,80})", text, flags=re.I)
    if match:
        desc = match.group(1)
        desc = re.split(r"\s+(?:eur|euro|€|di\s+\d|\d{2})", desc, flags=re.I)[0]
        desc = re.sub(r"\b(?:mila|thousand|euro|eur)\b.*", "", desc, flags=re.I).strip()
        if len(desc) >= 3:
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

    if ("controlla" in lowered or "controllo" in lowered) and "fattur" in lowered:
        return PlanResult(
            ok=True,
            summary="Assegno il controllo fatture (sola lettura) all'Agent PC-PAGAMENTI.",
            tasks=[
                PlannedTask(
                    goal="Controllare le fatture, senza modificarle",
                    capability="invoice_check",
                    args={"scope": "fatture_da_controllare"},
                    risk=Risk.LOW,
                    needs_approval=False,
                )
            ],
        )

    if "fattura" in lowered or re.search(r"\binvoice\b", lowered):
        client = _client_name(raw) or _client_name(lowered) or "Mario Rossi"
        net = _money(raw) or _money(lowered) or 1500.0
        description = _description(raw)
        return PlanResult(
            ok=True,
            summary=(
                f"Mando PC-FATTURE: apre il gestionale, scrive la fattura a {client} "
                f"per {description}, € {net:,.2f} + IVA. Poi ti chiedo conferma prima di emetterla."
            ),
            tasks=[
                PlannedTask(
                    goal=f"Aprire il gestionale e compilare la fattura a {client} per {description}",
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

    if _looks_like_email(raw):
        if _wants_real_email_send(raw):
            return PlanResult(
                ok=False,
                summary="Non invio email o PEC da qui. Posso solo preparare una bozza su PC-EMAIL.",
                denied=True,
                deny_reason="L'invio vero resta bloccato.",
            )
        to = _email_to(raw)
        body = _email_body(raw)
        subject = body[:80] if body != raw else "Messaggio dallo studio"
        dest = to or "destinatario da scegliere"
        return PlanResult(
            ok=True,
            summary=f"Preparo una bozza email a {dest}, senza inviarla. Serve PC-EMAIL acceso.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare bozza email a {dest}",
                    capability="email_draft",
                    args={
                        "to": to,
                        "subject": subject,
                        "body": body,
                    },
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(word in lowered for word in ("f24",)):
        return PlanResult(
            ok=True,
            summary="Assegno la preparazione F24 all'Agent PC-F24. Non invio nulla: il programma Agenzia non è ancora collegato.",
            tasks=[
                PlannedTask(
                    goal="Preparare F24 in scadenza, senza inviarli",
                    capability="f24_prepare",
                    args={"period": "in_scadenza", "note": raw[:500]},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(word in lowered for word in ("pagamento", "bonifico", "paga ")):
        return PlanResult(
            ok=True,
            summary="Assegno la preparazione del pagamento all'Agent PC-PAGAMENTI. Nessun bonifico parte.",
            tasks=[
                PlannedTask(
                    goal="Preparare pagamento in bozza, senza eseguirlo",
                    capability="payment_prepare",
                    args={"reason": raw[:500], "beneficiary": "da definire", "amount_eur": _money(lowered) or 0},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if "pec" in lowered and any(word in lowered for word in ("invia", "manda", "spedisci")):
        return PlanResult(
            ok=False,
            summary="Pagamenti e invio PEC non sono abilitati.",
            denied=True,
            deny_reason="Solo preparazione. L'invio reale resta bloccato.",
        )

    return PlanResult(
        ok=False,
        summary=(
            "Non ho capito. PC-FATTURE è il PC delle fatture: clicca Fattura Gadducci, "
            "oppure scrivi: fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera."
        ),
        denied=False,
        deny_reason="",
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
