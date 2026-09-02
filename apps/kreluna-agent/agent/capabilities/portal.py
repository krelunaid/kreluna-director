"""Lavoro vero sul PC: apre il portale nel browser, aspetta il tuo login, compila, si ferma."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from kreluna_shared.crypto import sha256_hex
from kreluna_shared.programs import load_settings, portal_for_key

from agent.tools import mac_browser


def _open_local_app(path_value: str) -> None:
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not path.exists():
        raise RuntimeError("Il percorso del programma fatture non esiste più.")
    if sys.platform == "darwin":
        if path.suffix.lower() != ".app":
            raise RuntimeError("Il percorso fatture non indica un'app Mac valida.")
        subprocess.Popen(
            ["/usr/bin/open", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    if sys.platform == "win32":
        if path.suffix.lower() != ".exe":
            raise RuntimeError("Il percorso fatture non indica un programma Windows valido.")
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise RuntimeError("Windows non riesce ad aprire il programma fatture.")
        startfile(str(path))
        return
    raise RuntimeError("Il programma fatture locale è supportato su Mac e Windows.")


def _safe_portal_target_url(value: str) -> str:
    """Defend the Agent even if a stored portal address is corrupted."""

    clean = value.strip()
    if not clean:
        return ""
    if len(clean) > 1000 or any(char in clean for char in ("\x00", "\r", "\n")):
        raise RuntimeError("FORT_KNOX_LINK_PORTALE_NON_VALIDO")
    parsed = urlparse(clean)
    if (
        parsed.scheme.lower() not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("FORT_KNOX_LINK_PORTALE_NON_VALIDO")
    if parsed.scheme.lower() == "http" and parsed.hostname.lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise RuntimeError("FORT_KNOX_LINK_PORTALE_NON_SICURO")
    return clean


def prepare_invoice_portal(
    *,
    account_name: str = "",
    client_name: str,
    description: str,
    net_eur: float,
    vat_rate: float = 0.22,
    vat_note: str = "",
    runner: mac_browser.Runner | None = None,
    supported: Callable[[], bool] = mac_browser.is_supported,
    sleep: Callable[[float], None] = time.sleep,
    mover: Callable[..., bool] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Compila la bozza sul portale configurato e si ferma prima dell'invio."""

    check = cancel_check or (lambda: None)
    check()
    spec = portal_for_key("fatture-webdesk")
    if spec is None or not spec.configured:
        return {
            "configured": False,
            "filled": False,
            "sent": False,
            "message": "Percorso PC-FATTURE non ancora configurato: uso la prova locale.",
            "evidence": [],
        }
    if spec.app_path:
        _open_local_app(spec.app_path)
        return {
            "configured": True,
            "filled": False,
            "sent": False,
            "program": spec.app_path,
            "message": (
                "Ho aperto il programma fatture configurato. Per compilare i campi reali "
                "serve la mappa della sua schermata; intanto mostro la bozza locale."
            ),
            "evidence": [],
        }
    if not supported() and sys.platform == "win32":
        webbrowser.open(spec.url)
        return {
            "configured": True,
            "filled": False,
            "sent": False,
            "program": spec.url,
            "message": "Ho aperto il portale fatture su Windows; la mappa dei campi va completata.",
            "evidence": [],
        }
    if not supported():
        raise RuntimeError("Il portale fatture configurato richiede un Agent Mac o Windows.")

    settings = load_settings()
    run = runner or mac_browser.Runner()
    browser = mac_browser.pick_browser(run, settings.mac_browser)
    mac_browser.open_url(run, browser, spec.url)
    check()
    evidence = [_evidence(mac_browser.screenshot(run), "fatture-aperto", spec.key)]
    required = {"client_name", "description", "net_eur"}
    if not required.issubset(spec.invoice_fields):
        customer_search_ready = all(
            spec.customer_search_fields.get(key)
            for key in ("filter_type", "query", "result_rows", "access_button")
        )
        customer_create_ready = all(
            spec.customer_create_fields.get(key)
            for key in ("customer_type", "tax_code", "business_name", "legal_address", "recipient_code")
        )
        missing_pages = []
        if not customer_search_ready:
            missing_pages.append("ricerca cliente in Servizi SMART")
        if not customer_create_ready:
            missing_pages.append("Clienti > Crea nuovo")
        missing_pages.append("Fatture > Crea nuovo")
        return {
            "configured": True,
            "filled": False,
            "sent": False,
            "program": spec.url,
            "message": (
                "Ho aperto il percorso fatture. Prima della compilazione cerchero il cliente e, "
                "solo se manca, preparero la sua anagrafica fermandomi prima di Salva. "
                "Mostra all'Agent queste pagine: " + "; ".join(missing_pages) + "."
            ),
            "customer_search_ready": customer_search_ready,
            "customer_create_ready": customer_create_ready,
            "evidence": evidence,
        }

    first = spec.invoice_fields["client_name"]
    waited = 0
    while not mac_browser.field_is_there(run, browser, first) and waited < settings.wait_for_login_seconds:
        check()
        sleep(settings.poll_seconds)
        waited += settings.poll_seconds
    if not mac_browser.field_is_there(run, browser, first):
        return {
            "configured": True,
            "filled": False,
            "sent": False,
            "program": spec.url,
            "message": f"{spec.name}: completa il login a mano, poi riprova.",
            "evidence": evidence,
        }
    where = mac_browser.current_url(run, browser)
    if not mac_browser.same_site(spec.url, where):
        return {
            "configured": True,
            "filled": False,
            "sent": False,
            "program": spec.url,
            "message": "La pagina davanti non è il portale fatture configurato: non scrivo niente.",
            "evidence": evidence,
        }

    values = {
        "account_name": account_name,
        "client_name": client_name,
        "description": description,
        "net_eur": f"{net_eur:.2f}",
        "vat_rate": f"{vat_rate * 100:g}",
        "vat_note": vat_note,
    }
    moved = False
    for name, selector in spec.invoice_fields.items():
        check()
        value = values.get(name, "")
        if not selector or not value:
            continue
        if mover is None:
            written, visible = mac_browser.fill_field_visible(run, browser, selector, value)
        else:
            written, visible = mac_browser.fill_field_visible(
                run,
                browser,
                selector,
                value,
                mover=mover,
            )
        if not written:
            return {
                "configured": True,
                "filled": False,
                "sent": False,
                "program": spec.url,
                "message": f"Il campo {name} è cambiato: mi fermo senza inviare.",
                "evidence": evidence,
            }
        moved = moved or visible
    evidence.append(_evidence(mac_browser.screenshot(run), "fattura-compilata", spec.key))
    return {
        "configured": True,
        "filled": True,
        "sent": False,
        "mouse_visible": moved,
        "program": spec.url,
        "message": "Bozza compilata. Mi sono fermato prima di Salva/Emetti/Invia.",
        "evidence": evidence,
    }


def _evidence(png: bytes, step: str, portal_key: str) -> dict[str, Any]:
    return {
        "kind": "screenshot",
        "sha256": sha256_hex(png),
        "png": png,
        "metadata": {"step": step, "portal": portal_key, "live": True, "sent": False},
    }


def learn_portal(
    portal: str,
    *,
    runner: mac_browser.Runner | None = None,
    supported: Callable[[], bool] = mac_browser.is_supported,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Guarda la pagina che hai davanti e scrive i nomi dei campi. Non tocca niente."""

    check = cancel_check or (lambda: None)
    check()
    spec = portal_for_key(portal)
    if spec is None:
        raise ValueError(f"PORTALE_SCONOSCIUTO:{portal}")
    if not supported():
        raise RuntimeError("Questo passo legge il browser di un Mac. Su questo PC non è disponibile.")

    settings = load_settings()
    run = runner or mac_browser.Runner()
    browser = mac_browser.pick_browser(run, settings.mac_browser)
    page = mac_browser.page_fields(run, browser)
    check()
    campi = page.get("campi") or []
    proposte = [
        {
            "nome": item.get("label") or item.get("placeholder") or item.get("aria") or item.get("name") or item.get("testo"),
            "tipo": item.get("tag"),
            "selettore": mac_browser.suggest_selector(item),
        }
        for item in campi
    ]
    scritti = [p for p in proposte if p["tipo"] in {"input", "textarea", "select"}]
    return {
        "ok": True,
        "live": True,
        "sent": False,
        "portal": spec.name,
        "pagina": page.get("url") or "",
        "titolo": page.get("titolo") or "",
        "campi_trovati": len(campi),
        "campi": scritti[:20],
        "bottoni": [p for p in proposte if p["tipo"] == "button"][:10],
        "message": (
            f'Ho guardato "{page.get("titolo") or "la pagina"}" e ho trovato {len(scritti)} campi. '
            "Non ho scritto e non ho cliccato niente."
        ),
        "evidence": [_evidence(mac_browser.screenshot(run), "pagina-studiata", portal)],
    }


def open_portal(
    portal: str,
    query: str = "",
    use_saved_access: bool = False,
    *,
    director_url: str = "",
    device_id: str | None = None,
    task_id: str = "",
    sign_request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    runner: mac_browser.Runner | None = None,
    supported: Callable[[], bool] = mac_browser.is_supported,
    sleep: Callable[[float], None] = time.sleep,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    check = cancel_check or (lambda: None)
    check()
    spec = portal_for_key(portal)
    if spec is None:
        raise ValueError(f"PORTALE_SCONOSCIUTO:{portal}")
    target_url = spec.url if spec.configured and not spec.app_path else ""
    if use_saved_access:
        if not director_url or not device_id or not task_id or sign_request is None:
            raise RuntimeError("CASSAFORTE_AGENT_NON_AUTORIZZATA")
        location_path = "/agent/portal-location"
        location_response = httpx.post(
            f"{director_url.rstrip('/')}{location_path}",
            json=sign_request(location_path, {"device_id": device_id, "task_id": task_id}),
            timeout=15,
        )
        if not location_response.is_success:
            try:
                detail = str(location_response.json().get("detail") or "Accesso non disponibile")
            except (ValueError, AttributeError):
                detail = "Accesso non disponibile"
            raise RuntimeError(detail)
        saved_target = _safe_portal_target_url(
            str(location_response.json().get("portal_url") or "")
        )
        if saved_target:
            target_url = saved_target
    if not spec.configured and not target_url:
        raise RuntimeError(
            f"{spec.name}: link non configurato. Inseriscilo in Fort Knox."
        )
    if spec.app_path and not target_url:
        _open_local_app(spec.app_path)
        return {
            "ok": True,
            "live": True,
            "sent": False,
            "filled": False,
            "browser": "programma locale",
            "portal": spec.name,
            "url": "",
            "query": query,
            "message": (
                f"Ho aperto {spec.name}. Il login resta manuale e non ho premuto Salva o Invia."
            ),
            "evidence": [],
        }
    if not supported() and sys.platform == "win32":
        webbrowser.open(target_url)
        return {
            "ok": True,
            "live": True,
            "sent": False,
            "filled": False,
            "browser": "predefinito Windows",
            "portal": spec.name,
            "url": target_url,
            "query": query,
            "message": (
                f"Ho aperto {spec.name} sul PC Windows. "
                + (
                    "Per sicurezza Fort Knox non compila ancora questo browser: inserisci l'accesso e l'OTP a mano. "
                    if use_saved_access
                    else "Completa il login a mano. "
                )
                + "Non ho inviato, scaricato o pagato nulla."
            ),
            "evidence": [],
        }
    if not supported():
        raise RuntimeError(
            "Questo passo muove il browser di un Mac. Su questo PC non è disponibile: "
            "il lavoro resta da fare a mano."
        )

    settings = load_settings()
    run = runner or mac_browser.Runner()
    browser = mac_browser.pick_browser(run, settings.mac_browser)
    evidence: list[dict[str, Any]] = []

    mac_browser.open_url(run, browser, target_url)
    check()
    evidence.append(_evidence(mac_browser.screenshot(run), "portale-aperto", portal))

    def stop(
        step: str,
        message: str,
        filled: bool = False,
        *,
        capture: bool = True,
    ) -> dict[str, Any]:
        if capture:
            evidence.append(_evidence(mac_browser.screenshot(run), step, portal))
        return {
            "ok": True,
            "live": True,
            "sent": False,
            "filled": filled,
            "browser": browser,
            "portal": spec.name,
            "url": target_url,
            "query": query,
            "message": message,
            "evidence": evidence,
        }

    if use_saved_access:
        if not spec.username_field or not spec.password_field:
            return stop(
                "accesso-non-supportato",
                f"{spec.name}: questo accesso resta manuale. SPID, CNS, CIE e smart card non vengono compilati.",
            )
        where = mac_browser.current_url(run, browser)
        if not mac_browser.same_site(target_url, where):
            return stop(
                "sito-sbagliato",
                f"Sul {browser} adesso c'è un altro sito, non {spec.name}. Non uso Fort Knox.",
            )
        sleep(settings.poll_seconds)
        has_username = mac_browser.field_is_there(run, browser, spec.username_field)
        has_password = mac_browser.field_is_there(run, browser, spec.password_field)
        if not has_username or not has_password:
            return stop(
                "campi-login-non-trovati",
                f"{spec.name}: non riconosco i campi di accesso. Non ho richiesto né mostrato la password.",
            )
        path = "/agent/credential-lease"
        response = httpx.post(
            f"{director_url.rstrip('/')}{path}",
            json=sign_request(path, {"device_id": device_id, "task_id": task_id}),
            timeout=15,
        )
        if not response.is_success:
            try:
                detail = str(response.json().get("detail") or "Accesso non disponibile")
            except (ValueError, AttributeError):
                detail = "Accesso non disponibile"
            raise RuntimeError(detail)
        credentials = response.json()
        username = str(credentials.get("username") or "")
        secret = str(credentials.get("secret") or "")
        if not username or not secret:
            raise RuntimeError("CASSAFORTE_ACCESSO_VUOTO")
        username_written = mac_browser.fill_field(run, browser, spec.username_field, username)
        password_written = mac_browser.fill_field(run, browser, spec.password_field, secret)
        credentials["username"] = ""
        credentials["secret"] = ""
        username = ""
        secret = ""
        if not username_written or not password_written:
            mac_browser.fill_field(run, browser, spec.username_field, "")
            mac_browser.fill_field(run, browser, spec.password_field, "")
            return stop(
                "accesso-non-compilato",
                f"{spec.name}: i campi sono cambiati. Ho ripulito ciò che avevo scritto e mi sono fermato.",
                capture=False,
            )
        return stop(
            "accesso-compilato",
            f"{spec.name}: accesso compilato da Fort Knox. Clicca tu per entrare; io non invio il modulo.",
            filled=True,
            capture=False,
        )

    waited = 0
    found = mac_browser.field_is_there(run, browser, spec.field) if spec.field else False
    while not found and waited < settings.wait_for_login_seconds:
        check()
        sleep(settings.poll_seconds)
        waited += settings.poll_seconds
        found = mac_browser.field_is_there(run, browser, spec.field)

    if not found:
        return stop(
            "aspetto-login",
            f"Ho aperto {spec.name} sul tuo schermo. {spec.login_note} "
            "Quando sei dentro, richiedimelo di nuovo e compilo io.",
        )

    # Prima di scrivere: la pagina davanti deve essere quella del portale.
    where = mac_browser.current_url(run, browser)
    if not mac_browser.same_site(target_url, where):
        return stop(
            "sito-sbagliato",
            f"Sul {browser} adesso c'è un altro sito, non {spec.name}. "
            "Non scrivo niente per non sbagliare finestra: apri la scheda giusta e richiedimelo.",
        )

    if not query:
        return stop("pronto", f"{spec.name} è aperto e pronto. Non ho scritto niente.")

    written = mac_browser.fill_field(run, browser, spec.field, query)
    if not written:
        return stop("campo-sparito", f"{spec.name}: il campo di ricerca non c'è più. Non ho scritto niente.")

    return stop(
        "compilato",
        f'{spec.name}: ho scritto "{query}" nel campo di ricerca e mi sono fermato. '
        "Non ho premuto invio, non ho scaricato niente.",
        filled=True,
    )
