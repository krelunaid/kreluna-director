"""Lavoro vero sul PC: apre il portale nel browser, aspetta il tuo login, compila, si ferma."""

from __future__ import annotations

import sys
import time
import webbrowser
from collections.abc import Callable
from typing import Any

import httpx
from kreluna_shared.crypto import sha256_hex
from kreluna_shared.programs import load_settings, portal_for_key

from agent.tools import mac_browser


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
) -> dict[str, Any]:
    """Guarda la pagina che hai davanti e scrive i nomi dei campi. Non tocca niente."""

    spec = portal_for_key(portal)
    if spec is None:
        raise ValueError(f"PORTALE_SCONOSCIUTO:{portal}")
    if not supported():
        raise RuntimeError("Questo passo legge il browser di un Mac. Su questo PC non è disponibile.")

    settings = load_settings()
    run = runner or mac_browser.Runner()
    browser = mac_browser.pick_browser(run, settings.mac_browser)
    page = mac_browser.page_fields(run, browser)
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
    signature: str = "",
    runner: mac_browser.Runner | None = None,
    supported: Callable[[], bool] = mac_browser.is_supported,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    spec = portal_for_key(portal)
    if spec is None:
        raise ValueError(f"PORTALE_SCONOSCIUTO:{portal}")
    if not supported() and sys.platform == "win32":
        webbrowser.open(spec.url)
        return {
            "ok": True,
            "live": True,
            "sent": False,
            "filled": False,
            "browser": "predefinito Windows",
            "portal": spec.name,
            "url": spec.url,
            "query": query,
            "message": (
                f"Ho aperto {spec.name} sul PC Windows. "
                + (
                    "Per sicurezza la Cassaforte non compila ancora questo browser: inserisci l'accesso e l'OTP a mano. "
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

    mac_browser.open_url(run, browser, spec.url)
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
            "url": spec.url,
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
        if not mac_browser.same_site(spec.url, where):
            return stop(
                "sito-sbagliato",
                f"Sul {browser} adesso c'è un altro sito, non {spec.name}. Non uso la Cassaforte.",
            )
        sleep(settings.poll_seconds)
        has_username = mac_browser.field_is_there(run, browser, spec.username_field)
        has_password = mac_browser.field_is_there(run, browser, spec.password_field)
        if not has_username or not has_password:
            return stop(
                "campi-login-non-trovati",
                f"{spec.name}: non riconosco i campi di accesso. Non ho richiesto né mostrato la password.",
            )
        if not director_url or not device_id or not task_id or not signature:
            raise RuntimeError("CASSAFORTE_AGENT_NON_AUTORIZZATA")
        response = httpx.post(
            f"{director_url.rstrip('/')}/agent/credential-lease",
            json={"device_id": device_id, "task_id": task_id, "signature": signature},
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
            f"{spec.name}: accesso compilato dalla Cassaforte. Clicca tu per entrare; io non invio il modulo.",
            filled=True,
            capture=False,
        )

    waited = 0
    found = mac_browser.field_is_there(run, browser, spec.field) if spec.field else False
    while not found and waited < settings.wait_for_login_seconds:
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
    if not mac_browser.same_site(spec.url, where):
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
