from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
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
        flags=re.IGNORECASE,
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
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return _parse_amount(match.group(1) or match.group(2))


NOT_A_NAME = {
    "mano",
    "fine",
    "mese",
    "anno",
    "giorni",
    "credito",
    "debito",
    "posta",
    "rate",
    "saldo",
    "acconto",
    "scadenza",
    "manodopera",
    "consulenza",
    "prestazione",
    "iva",
    "euro",
    "cliente",
    "ditta",
    "impresa",
    "societa",
    "società",
    "davvero",
    "mano d'opera",
}


KNOWN_CLIENTS = (
    ("andrea gadducci", "Andrea Gadducci"),
    ("gadducci", "Andrea Gadducci"),
    ("verdi luigi", "Verdi Luigi"),
    ("mario rossi", "Mario Rossi"),
)

COMPANY_SUFFIXES = {"srl", "spa", "snc", "sas", "ss", "srls"}


def _display_name(value: str) -> str:
    words = [word for word in value.strip(" ,.;:-").split() if word]
    return " ".join(word.upper() if word.lower() in COMPANY_SUFFIXES else word.title() for word in words)


def _canonical_known_name(value: str) -> str:
    """Corregge soltanto refusi molto vicini a un cliente noto, mai nomi arbitrari."""

    candidate = " ".join(value.lower().split())
    for needle, name in KNOWN_CLIENTS:
        if candidate == needle or SequenceMatcher(None, candidate, needle).ratio() >= 0.88:
            return name
    return _display_name(value)


def _invoice_parties(text: str) -> tuple[str, str]:
    """Separa azienda emittente e destinatario in frasi come "per X ... a Y"."""

    amount_then_recipient = re.search(
        r"(?:\d[\d. ,]{0,18}\s*(?:euro|eur|€)|(?:euro|eur|€)\s*\d[\d. ,]{0,18})"
        r"\s+(?:a|ad|al\s+cliente)\s+"
        r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'&.-]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'&.-]*){0,3}?)"
        r"(?=\s+(?:senza|con|iva|non\s+imponibile|esenzion|dichiarazione)|[,.]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not amount_then_recipient:
        return "", ""
    recipient = _canonical_known_name(amount_then_recipient.group(1))
    before_amount = text[: amount_then_recipient.start()]
    account_match = re.search(
        r"\bfattura\s+(?:per|di)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'&.-]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'&.-]*){0,3}?)"
        r"(?=\s+(?:di|da|per)\s+|\s+\d|[,.]|$)",
        before_amount,
        flags=re.IGNORECASE,
    )
    account = _canonical_known_name(account_match.group(1)) if account_match else ""
    return account, recipient


def _client_name(text: str) -> str | None:
    lowered = text.lower()
    for needle, name in KNOWN_CLIENTS:
        if needle in lowered:
            return name
    patterns = [
        r"(?:fattura|invoice)(?:\s+demo)?\s+(?:ad|al cliente|a|per|pae|pre|pe|to)\s+([A-Za-zÀ-ÿ']+(?:\s+[A-Za-zÀ-ÿ']+){0,3}?)(?=\s+(?:per|di|for|da|euro|eur|€|\d)|[,.]|$)",
        r"(?:per)\s+([A-Za-zÀ-ÿ']+)(?:\s+di\s+)",
        r"(?:cliente)\s+([A-Za-zÀ-ÿ']+\s+[A-Za-zÀ-ÿ']+)",
        r"(?:la\s+ditta|l['’]impresa|la\s+societ[aà])\s+([A-Za-zÀ-ÿ']+(?:\s+[A-Za-zÀ-ÿ']+)?)",
        r"(?:per|di)\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ']{2,}(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ']+)?)\s*[.!?]?\s*$",
        # "…a giorgio tesi", anche scritto tutto minuscolo: due parole a fine frase.
        r"\b(?:a|ad|al|per|pae|pre|pe)\s+([A-Za-zÀ-ÿ']{3,}\s+[A-Za-zÀ-ÿ']{3,})\s*[.!?]?\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            words = match.group(1).split()
            name = _display_name(" ".join(words))
            if name.lower() in {"demo", "una", "la", "the", "fattura"} | NOT_A_NAME:
                continue
            if any(word.lower() in NOT_A_NAME for word in words):
                continue
            return name
    return None


def _looks_like_email(text: str) -> bool:
    return bool(re.search(r"\b(?:e-?mail|mail|posta|pec)\b", text, flags=re.IGNORECASE))


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
        flags=re.IGNORECASE,
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
    match = re.search(r"(?:dicendo|che dice|con testo|testo)\s*:?\s*(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        body = match.group(1).strip().strip(" .\"'")
        if body:
            return body
    return text.strip()


def _description(text: str, default: str = "Consulenza") -> str:
    lowered = text.lower()
    words = re.findall(r"[a-zà-ÿ']{5,}", lowered)
    looks_like_manodopera = any(SequenceMatcher(None, word, "manodopera").ratio() >= 0.72 for word in words)
    if "manodopera" in lowered or "manpower" in lowered or looks_like_manodopera:
        return "Manodopera"
    if re.search(r"\bconsulenza\b", lowered):
        return "Consulenza"
    match = re.search(r"(?:per|for|di)\s+([^,.]{3,80})", text, flags=re.IGNORECASE)
    if match:
        desc = match.group(1)
        desc = re.split(r"\s+(?:eur|euro|€|di\s+\d|\d{2})", desc, flags=re.IGNORECASE)[0]
        desc = re.sub(r"\b(?:mila|thousand|euro|eur)\b.*", "", desc, flags=re.IGNORECASE).strip()
        if len(desc) >= 3:
            return desc.strip().capitalize()
    return default


def _vat_details(text: str) -> tuple[float, str, bool]:
    lowered = text.lower().replace("’", "'")
    declaration = bool(re.search(r"dichiarazione\s+d(?:i|[' ]?)\s*intento", lowered))
    without_vat = declaration or any(
        phrase in lowered
        for phrase in ("senza iva", "iva 0", "iva zero", "non imponibile", "esenzione iva", "esente iva")
    )
    if without_vat:
        note = "Dichiarazione d'intento" if declaration else "Operazione senza IVA"
        return 0.0, note, True
    explicit = re.search(r"\biva\s*(\d{1,2}(?:[.,]\d+)?)\s*%?", lowered)
    if explicit:
        rate = float(explicit.group(1).replace(",", ".")) / 100
        return rate, f"IVA {rate * 100:g}%", True
    return 0.22, "", False


def _amount_in_reply(text: str) -> float | None:
    """Importo nella risposta: anche solo '5000' o 'sì, 5.000'."""

    found = _money(text)
    if found is not None:
        return found
    cleaned = re.sub(r"^(?:s[iì]|ok|va\s*bene)[,.\s]*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*€\s*$", "", cleaned).strip()
    if re.fullmatch(r"\d{1,7}(?:[.,]\d{3})*(?:[.,]\d{1,2})?", cleaned):
        return _parse_amount(cleaned)
    return None


LIVE_PORTALS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("f24-ipsoa", "F24 su IPSOA", ("f24", "delega f24", "deleghe f24")),
    ("visure-cgn", "Visure su CGN", ("visura", "visure")),
    ("durc-inps", "DURC su INPS", ("durc", "inps")),
    ("contratti-ade", "Contratti su AdE", ("contratt", "samuele")),
    ("camerali-cgn", "Pratiche camerali su CGN", ("cameral", "comunica")),
    ("fatture-webdesk", "Fatture su Webdesk", ("fattur", "webdesk")),
)

LIVE_WORDS = (
    "vero",
    "vera",
    "davvero",
    "apri il sito",
    "apri il portale",
    "nel browser",
    "impara",
    "imparare",
    "guarda la pagina",
    "studia la pagina",
)

TEACH_WORDS = ("impara", "imparare", "guarda la pagina", "studia la pagina", "insegn")


def _wants_to_teach(lowered: str) -> bool:
    return any(word in lowered for word in TEACH_WORDS)


def _live_portal(lowered: str) -> tuple[str, str] | None:
    """Il lavoro vero si chiede a parole: 'visura vera', 'apri il sito INPS'."""

    if not any(word in lowered for word in LIVE_WORDS):
        return None
    for key, name, needles in LIVE_PORTALS:
        if any(needle in lowered for needle in needles):
            return key, name
    return None


HELP_PHRASES = (
    "cosa sai fare",
    "che cosa sai fare",
    "cosa puoi fare",
    "che cosa puoi fare",
    "cosa riesci a fare",
    "che sai fare",
    "come funzioni",
    "come funziona",
    "aiuto",
    "help",
    "istruzioni",
)


def _asks_what_i_can_do(lowered: str) -> bool:
    if any(phrase in lowered for phrase in HELP_PHRASES):
        return True
    # "puoi fare fatture?", "sai fare i DURC?": è una domanda, non un ordine.
    stripped = lowered.strip()
    asks = bool(re.match(r"^(?:mi\s+)?(?:puoi|sai|riesci\s+a|riusciresti\s+a)\b", stripped))
    return asks and stripped.endswith("?")


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

    if _asks_what_i_can_do(lowered):
        return PlanResult(
            ok=False,
            summary=(
                "Ecco cosa so fare, un PC per lavoro:\n"
                "• Fatture (Webdesk / AdE): «fattura a Gadducci 5.000 euro di manodopera»\n"
                "• Deleghe F24 (IPSOA): «prepara gli F24»\n"
                "• Contabilità (AdE → IPSOA): «scarica le fatture in IPSOA per Gadducci»\n"
                "• Pratiche camerali (CGN, ComUnica): «pratica camerale per Gadducci»\n"
                "• Contratti (AdE di Samuele): «contratto per Gadducci»\n"
                "• Richieste DURC (INPS): «DURC per Gadducci»\n"
                "• Visure (CGN): «visura per Gadducci»\n"
                "Per lavorare sul sito vero aggiungi «vera» o «apri il sito», "
                "per esempio: «apri il sito CGN e fai la visura vera per Gadducci».\n"
                "Importi e nomi non li invento: se mancano, te li chiedo. "
                "Niente invii, niente pagamenti: prima chiedo Approva."
            ),
            denied=False,
            deny_reason="",
            source="deterministic-help",
        )

    notepad = re.search(
        r"(?:apri\s+)?(?:il\s+)?blocco\s+note.*?(?:scrivi|testo)\s*:?\s*[\"']?(.+?)[\"']?$",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if notepad or ("blocco note" in lowered and "scrivi" in lowered):
        written = notepad.group(1).strip() if notepad else raw
        written = written.strip(" .\"'")
        if "scrivi" in lowered:
            after = re.split(r"scrivi\s*:?\s*", raw, flags=re.IGNORECASE, maxsplit=1)
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

    live = _live_portal(lowered)
    if live is not None and _wants_to_teach(lowered):
        portal, portal_name = live
        return PlanResult(
            ok=True,
            summary=(
                f"Studio la pagina di {portal_name} che hai davanti sul PC e ti scrivo i nomi dei campi. "
                "Non scrivo e non clicco niente."
            ),
            tasks=[
                PlannedTask(
                    goal=f"Imparare la pagina di {portal_name}",
                    capability="portal_learn",
                    args={"portal": portal},
                    risk=Risk.LOW,
                    needs_approval=False,
                )
            ],
        )

    if live is not None:
        portal, portal_name = live
        client = _client_name(raw) or _client_name(lowered) or ""
        use_saved_access = any(
            phrase in lowered
            for phrase in (
                "accesso salvato",
                "credenziali salvate",
                "password salvata",
                "usa la cassaforte",
                "usa fort knox",
                "fort knox",
            )
        )
        return PlanResult(
            ok=True,
            summary=(
                f"Lavoro vero su {portal_name}: apro il sito nel browser del PC"
                + (f" e cerco {client}" if client else "")
                + (
                    ". Compilo l'accesso da Fort Knox e mi fermo prima del login."
                    if use_saved_access
                    else ". Il login lo fai tu."
                )
                + " Non premo invio e non scarico niente."
            ),
            tasks=[
                PlannedTask(
                    goal=f"Aprire {portal_name} sul PC" + (f" e cercare {client}" if client else ""),
                    capability="portal_open",
                    args={
                        "portal": portal,
                        "query": client,
                        "use_saved_access": use_saved_access,
                    },
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if "f24" in lowered or "deleghe f24" in lowered or "delega f24" in lowered:
        return PlanResult(
            ok=True,
            summary="Mando PC-F24: creazione in IPSOA. Invio Telematico non parte.",
            tasks=[
                PlannedTask(
                    goal="Preparare F24 in IPSOA, senza inviarli",
                    capability="f24_prepare",
                    args={"period": "in_scadenza", "note": raw[:500]},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(
        word in lowered
        for word in (
            "contabilit",
            "ipsoa",
            "p7m",
            "importatore",
            "scarico fattur",
            "carico fattur",
            "cassetto fiscale",
        )
    ):
        client = _client_name(raw) or _client_name(lowered) or "Cliente"
        return PlanResult(
            ok=True,
            summary=(
                f"Mando PC-CONTABILITA per {client}: scarico AdE XML/P7M, carico IPSOA, "
                "importatore contabile. Demo: niente SPID."
            ),
            tasks=[
                PlannedTask(
                    goal=f"Preparare lo scarico e il carico IPSOA per {client}",
                    capability="contabilita_prepare",
                    args={"client_name": client, "notes": raw[:500], "period": ""},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if "durc" in lowered or ("sito inps" in lowered):
        client = _client_name(raw) or _client_name(lowered) or "Cliente"
        return PlanResult(
            ok=True,
            summary=f"Mando PC-DURC: sito INPS per {client}. Demo: niente SPID, nessuna richiesta vera.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare richiesta DURC per {client}",
                    capability="durc_prepare",
                    args={"client_name": client, "notes": raw[:500]},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(word in lowered for word in ("visura", "visure")):
        client = _client_name(raw) or _client_name(lowered) or "Cliente"
        return PlanResult(
            ok=True,
            summary=f"Mando PC-VISURE: sito CGN per {client}. Nessun download reale.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare visura per {client}",
                    capability="visure_prepare",
                    args={"client_name": client, "notes": raw[:500], "visura_type": ""},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if any(
        word in lowered
        for word in ("cameral", "comunica", "camera di commercio", "registro imprese", "camera commercio")
    ):
        client = _client_name(raw) or _client_name(lowered) or "Cliente"
        return PlanResult(
            ok=True,
            summary=f"Mando PC-CAMERALI: sito CGN e Desktop ComUnica per {client}. Nessun invio.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare pratica camerale per {client}",
                    capability="camera_prepare",
                    args={"client_name": client, "notes": raw[:500], "practice_type": ""},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if "samuele" in lowered or (
        any(word in lowered for word in ("contratto", "contratti")) and "fattur" not in lowered
    ):
        client = _client_name(raw) or _client_name(lowered) or "Cliente"
        return PlanResult(
            ok=True,
            summary=f"Mando PC-CONTRATTI: sito AdE di Samuele per {client}. Nessun invio.",
            tasks=[
                PlannedTask(
                    goal=f"Preparare contratto per {client}",
                    capability="contratti_prepare",
                    args={"client_name": client, "notes": raw[:500], "contract_type": ""},
                    risk=Risk.MEDIUM,
                    needs_approval=False,
                )
            ],
        )

    if ("controlla" in lowered or "controllo" in lowered) and "fattur" in lowered:
        return PlanResult(
            ok=True,
            summary="Assegno il controllo fatture (sola lettura) all'Agent PC-CONTABILITA.",
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
        if _about_this_invoice(lowered) and not (_client_name(raw) or _money(raw)):
            return PlanResult(
                ok=False,
                summary=(
                    "Non ho una fattura aperta in questo momento. "
                    "Scrivi per esempio: fattura a Andrea Gadducci per 5.000 euro di manodopera."
                ),
                denied=False,
                deny_reason="",
                source="deterministic-ask",
            )
        account, recipient = _invoice_parties(raw)
        client = recipient or _client_name(raw) or _client_name(lowered) or ""
        net = _money(raw) or _money(lowered)
        description = _description(raw)
        vat_rate, vat_note, _vat_explicit = _vat_details(raw)
        if client and (description.lower() in client.lower() or client.lower() in description.lower()):
            description = ""
        missing = []
        if not client:
            missing.append("il cliente")
        if net is None:
            missing.append("l'importo")
        if not description:
            missing.append("il lavoro")
        if missing:
            who = client or "Andrea Gadducci"
            return PlanResult(
                ok=False,
                summary=(
                    f"Mi manca {' e '.join(missing)}. Non invento niente. "
                    f"Scrivi per esempio: fattura a {who} per 5.000 euro di manodopera."
                ),
                denied=False,
                deny_reason="",
                source="deterministic-ask",
                pending={
                    "capability": "invoice_prepare_demo",
                    "account_name": account,
                    "client_name": client,
                    "description": description,
                    "net_eur": net,
                    "vat_rate": vat_rate,
                    "vat_note": vat_note,
                },
            )
        return invoice_plan(
            client,
            description,
            net,
            account_name=account,
            vat_rate=vat_rate,
            vat_note=vat_note,
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
            "Non ho capito. Prova: Fattura Gadducci, prepara F24, scarica fatture in IPSOA, "
            "visura, DURC, pratica camerale, contratto Samuele."
        ),
        denied=False,
        deny_reason="",
        source="deterministic-unknown",
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


def invoice_plan(
    client: str,
    description: str,
    net: float,
    *,
    account_name: str = "",
    vat_rate: float = 0.22,
    vat_note: str = "",
) -> PlanResult:
    account = f" per conto di {account_name}" if account_name else ""
    tax = f"IVA {vat_rate * 100:g}%"
    if vat_rate == 0:
        tax = f"senza IVA ({vat_note or 'operazione non imponibile'})"
    return PlanResult(
        ok=True,
        summary=(
            f"Mando PC-FATTURE (Webdesk / sito AdE, demo locale){account}: fattura a {client} "
            f"per {description}, € {net:,.2f}, {tax}. Poi ti chiedo conferma prima di emetterla."
        ),
        tasks=[
            PlannedTask(
                goal=f"Aprire il gestionale e compilare la fattura a {client} per {description}",
                capability="invoice_prepare_demo",
                args={
                    "account_name": account_name or None,
                    "client_name": client,
                    "description": description,
                    "net_eur": net,
                    "vat_rate": vat_rate,
                    "vat_note": vat_note,
                },
                risk=Risk.MEDIUM,
                needs_approval=False,
            )
        ],
    )


def complete_pending(pending: dict[str, Any], text: str) -> PlanResult | None:
    """Legge la tua risposta come risposta, non come richiesta nuova.

    Ritorna None se il messaggio non c'entra: allora si ricomincia da capo.
    """

    if (pending or {}).get("capability") != "invoice_prepare_demo":
        return None
    raw = text.strip()
    lowered = raw.lower()
    if any(phrase in lowered for phrase in DENY_PHRASES) or _asks_what_i_can_do(lowered):
        return None

    account = pending.get("account_name") or ""
    client = pending.get("client_name") or _client_name(raw) or _client_name(lowered) or ""
    net = pending.get("net_eur")
    if net is None:
        net = _amount_in_reply(raw) or _amount_in_reply(lowered)
    description = pending.get("description") or ""
    if not description:
        found = _description(raw, default="")
        if found and not (client and (found.lower() in client.lower() or client.lower() in found.lower())):
            description = found
    pending_rate = pending.get("vat_rate")
    vat_rate = float(pending_rate) if pending_rate is not None else 0.22
    vat_note = str(pending.get("vat_note") or "")
    reply_rate, reply_note, reply_explicit = _vat_details(raw)
    if reply_explicit:
        vat_rate, vat_note = reply_rate, reply_note

    if not client:
        # Una risposta breve senza verbi è probabilmente il nome del cliente.
        candidate = " ".join(word for word in raw.replace(",", " ").split() if word.lower() not in NOT_A_NAME)
        words = [w for w in candidate.split() if len(w) >= 3 and not any(ch.isdigit() for ch in w)]
        if 1 <= len(words) <= 4 and len(raw) <= 60:
            client = " ".join(words).title()

    missing = []
    if not client:
        missing.append("il cliente")
    if net is None:
        missing.append("l'importo")
    if not description:
        missing.append("il lavoro")

    if missing:
        return PlanResult(
            ok=False,
            summary=f"Ci siamo quasi: mi manca {' e '.join(missing)}.",
            denied=False,
            deny_reason="",
            source="deterministic-ask",
            pending={
                "capability": "invoice_prepare_demo",
                "account_name": account,
                "client_name": client,
                "description": description,
                "net_eur": net,
                "vat_rate": vat_rate,
                "vat_note": vat_note,
            },
        )
    return invoice_plan(
        client,
        description,
        float(net),
        account_name=account,
        vat_rate=vat_rate,
        vat_note=vat_note,
    )


THIS_INVOICE = (
    "questa fattura",
    "questa qui",
    "in fattura",
    "nella fattura",
    "stessa fattura",
    "su questa",
    "in questa",
)

TAX_NOTE = (
    "esenzione",
    "dichiarazione d'intento",
    "dichiarazione di intento",
    "senza iva",
    "non imponibile",
    "reverse charge",
    "iva 0",
    "iva zero",
    "plafond",
)


def _about_this_invoice(lowered: str) -> bool:
    return any(phrase in lowered for phrase in THIS_INVOICE)


def continue_open_invoice(invoice: dict[str, Any] | None, text: str) -> PlanResult | None:
    """Segue la fattura già aperta: esenzione IVA, 'in questa fattura', senza rifare tutto."""

    if not invoice:
        return None
    raw = text.strip()
    lowered = raw.lower()
    if any(phrase in lowered for phrase in DENY_PHRASES) or _asks_what_i_can_do(lowered):
        return None
    if _client_name(raw) and (_money(raw) or _amount_in_reply(raw)):
        return None
    new_job = any(
        word in lowered for word in ("visura", "durc", "f24", "cameral", "contratt", "ferma tutto", "contabilit")
    )
    if new_job and "fattur" not in lowered:
        return None
    tax = any(note in lowered for note in TAX_NOTE)
    refers = _about_this_invoice(lowered)
    if not tax and not refers:
        return None

    client = str(invoice.get("client_name") or "il cliente")
    net = invoice.get("net_eur")
    money = f", € {float(net):,.2f}" if net not in (None, "") else ""
    if tax:
        return PlanResult(
            ok=True,
            summary=(
                f"Ok, lo segno su questa fattura a {client}{money}: "
                "esenzione IVA / dichiarazione d'intento. "
                "In demo non mando niente all'Agenzia. Confermi da Approva, sulla destra."
            ),
            tasks=[],
            source="deterministic",
        )
    return PlanResult(
        ok=True,
        summary=(
            f"Resto su questa fattura a {client}{money}. Dimmi solo cosa cambiare: importo, lavoro o IVA."
        ),
        tasks=[],
        source="deterministic",
    )


def parse_llm_plan(payload: Any) -> PlanResult:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return PlanResult.model_validate(payload)
