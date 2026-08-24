"""Lavoro vero sul PC: apre il portale nel browser, aspetta il tuo login, compila, si ferma."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

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


def open_portal(
    portal: str,
    query: str = "",
    *,
    runner: mac_browser.Runner | None = None,
    supported: Callable[[], bool] = mac_browser.is_supported,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    spec = portal_for_key(portal)
    if spec is None:
        raise ValueError(f"PORTALE_SCONOSCIUTO:{portal}")
    if not supported():
        raise RuntimeError(
            "Questo passo muove il browser di un Mac. Su questo PC non è disponibile: "
            "il lavoro resta da fare a mano."
        )

    settings = load_settings()
    browser = settings.mac_browser
    run = runner or mac_browser.Runner()
    evidence: list[dict[str, Any]] = []

    mac_browser.open_url(run, browser, spec.url)
    evidence.append(_evidence(mac_browser.screenshot(run), "portale-aperto", portal))

    waited = 0
    found = mac_browser.field_is_there(run, browser, spec.field) if spec.field else False
    while not found and waited < settings.wait_for_login_seconds:
        sleep(settings.poll_seconds)
        waited += settings.poll_seconds
        found = mac_browser.field_is_there(run, browser, spec.field)

    if not found:
        evidence.append(_evidence(mac_browser.screenshot(run), "aspetto-login", portal))
        return {
            "ok": True,
            "live": True,
            "sent": False,
            "filled": False,
            "portal": spec.name,
            "url": spec.url,
            "message": (
                f"Ho aperto {spec.name} sul tuo schermo. {spec.login_note} "
                "Quando sei dentro, richiedimelo di nuovo e compilo io."
            ),
            "evidence": evidence,
        }

    written = mac_browser.fill_field(run, browser, spec.field, query) if query else False
    evidence.append(_evidence(mac_browser.screenshot(run), "compilato" if written else "pronto", portal))
    return {
        "ok": True,
        "live": True,
        "sent": False,
        "filled": written,
        "portal": spec.name,
        "url": spec.url,
        "query": query,
        "message": (
            f"{spec.name}: ho scritto \"{query}\" nel campo di ricerca e mi sono fermato. "
            "Non ho premuto invio, non ho scaricato niente."
            if written
            else f"{spec.name} è aperto e pronto. Non ho scritto niente."
        ),
        "evidence": evidence,
    }
