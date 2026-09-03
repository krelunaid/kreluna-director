"""Configurazione guidata del browser sul Mac, senza aggirare i permessi Apple."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

BROWSERS = (
    "Safari",
    "Google Chrome",
    "Microsoft Edge",
    "Brave Browser",
    "Chromium",
    "Vivaldi",
)
WEBDESK_LOGIN = "https://app.webdesk.it/Apps/Login/View"


Run = Callable[..., subprocess.CompletedProcess[str]]


def _run(command: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _apple_script(run: Run, script: str) -> subprocess.CompletedProcess[str]:
    return run(["/usr/bin/osascript", "-e", script], timeout=30)


def installed_browser(run: Run = _run) -> str | None:
    """Sceglie il browser realmente installato; Safari resta il ripiego del Mac."""

    for browser in BROWSERS:
        result = _apple_script(run, f'id of application "{browser}"')
        if result.returncode == 0:
            return browser
    return None


def permission_instructions(browser: str) -> str:
    if browser == "Safari":
        return (
            "Safari è già aperto: non devi aprire un altro programma.\n\n"
            "1. In alto a sinistra, accanto alla mela, clicca Safari.\n"
            "2. Clicca Impostazioni e poi Avanzate.\n"
            "3. Attiva Mostra funzionalità per sviluppatori web.\n"
            "4. Chiudi le Impostazioni. In alto apparirà il menu Sviluppo.\n"
            "5. Clicca Sviluppo > Consenti JavaScript dagli Apple Event.\n"
            "6. Torna qui e premi Ho attivato: controlla."
        )
    return (
        f"{browser} è già aperto: non devi aprire un altro programma.\n\n"
        "1. In alto clicca Visualizza.\n"
        "2. Apri Sviluppatore.\n"
        "3. Attiva Consenti JavaScript dagli Apple Event.\n"
        "4. Torna qui e premi Ho attivato: controlla."
    )


def control_is_ready(browser: str, run: Run = _run) -> bool:
    """Verifica davvero il comando usato dall'Agent, senza modificare la pagina."""

    if browser == "Safari":
        script = '''
tell application "Safari"
  if (count of windows) is 0 then return "NO_WINDOW"
  do JavaScript "document.title" in current tab of front window
end tell
return "READY"
'''
    else:
        script = f'''
tell application "{browser}"
  if (count of windows) is 0 then return "NO_WINDOW"
  tell active tab of front window to execute javascript "document.title"
end tell
return "READY"
'''
    result = _apple_script(run, script)
    return result.returncode == 0 and "READY" in result.stdout


def _dialog(run: Run, text: str, buttons: tuple[str, str], default: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    left, right = buttons
    script = (
        f'display dialog "{escaped}" buttons {{"{left}", "{right}"}} '
        f'default button "{default}" with title "Configura Kreluna Agent"'
    )
    result = _apple_script(run, script)
    if result.returncode != 0:
        return ""
    return result.stdout.strip().removeprefix("button returned:").strip()


def guide_browser_permissions(run: Run = _run) -> bool:
    """Apre il browser e accompagna l'utente nell'unico consenso non automatizzabile."""

    if sys.platform != "darwin":
        return True
    browser = installed_browser(run)
    if browser is None:
        _dialog(
            run,
            "Kreluna non trova Safari, Chrome, Edge o Brave. Installa un browser e riprova.",
            ("Chiudi", "OK"),
            "OK",
        )
        return False

    # Aprire una pagina e controllarne il titolo non compila e non invia alcun dato.
    run(["/usr/bin/open", "-a", browser, WEBDESK_LOGIN], timeout=15)
    if control_is_ready(browser, run):
        return True

    message = (
        f"Kreluna ha riconosciuto {browser}. Serve una sola autorizzazione.\n\n"
        f"{permission_instructions(browser)}\n\n"
        "Segui i numeri e poi premi il pulsante di controllo."
    )
    for _attempt in range(3):
        verify = "Ho attivato: controlla"
        if _dialog(run, message, ("Non ora", verify), verify) != verify:
            return False
        if control_is_ready(browser, run):
            _dialog(
                run,
                f"{browser} è pronto. Da ora Kreluna può preparare le schermate senza inviarle.",
                ("Chiudi", "Continua"),
                "Continua",
            )
            return True
        message = (
            "Il permesso non risulta ancora attivo.\n\n"
            f"{permission_instructions(browser)}\n\n"
            "Segui tutti i numeri e premi di nuovo Ho attivato: controlla."
        )
    return False
