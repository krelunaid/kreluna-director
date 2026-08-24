"""Guida il browser vero del Mac: apre, controlla l'indirizzo, scrive nel campo, fotografa.

Tre regole di questo file:
- il campo si trova nella pagina, non a coordinate del mouse;
- non si scrive niente se la pagina aperta non è quella del portale giusto;
- non si preme mai invio e non si invia mai un modulo.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

JS_MISSING = "NON_TROVATO"
CHROME_FAMILY = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium", "Vivaldi")
SAFARI = "Safari"


class MacControlError(RuntimeError):
    """Manca un permesso sul Mac, oppure il browser non risponde."""


@dataclass
class Runner:
    """Esegue osascript. Nei test si sostituisce con una finta."""

    timeout: float = 30.0

    def osascript(self, script: str) -> str:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0:
            raise MacControlError((result.stderr or "osascript non ha risposto").strip())
        return result.stdout.strip()

    def screencapture(self, path: Path) -> bytes:
        result = subprocess.run(
            ["screencapture", "-x", str(path)],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0 or not path.exists():
            raise MacControlError((result.stderr or "screencapture non ha risposto").strip())
        return path.read_bytes()


def is_supported() -> bool:
    return sys.platform == "darwin"


def _is_installed(runner: Runner, browser: str) -> bool:
    try:
        runner.osascript(f'id of application "{browser}"')
    except MacControlError:
        return False
    return True


def pick_browser(runner: Runner, preferred: str) -> str:
    """Usa il browser scelto nella configurazione, se c'è. Altrimenti quello che c'è."""

    for candidate in (preferred, *CHROME_FAMILY, SAFARI):
        if candidate and _is_installed(runner, candidate):
            return candidate
    raise MacControlError(
        "Non trovo un browser da guidare. Installa Google Chrome, oppure scrivi "
        "'mac_browser: Safari' in policies/programs.yaml."
    )


def _is_safari(browser: str) -> bool:
    return browser.strip().lower() == "safari"


def open_url_script(browser: str, url: str) -> str:
    if _is_safari(browser):
        return f'''
tell application "{browser}"
  activate
  if (count of windows) is 0 then
    make new document
  end if
  set URL of current tab of front window to "{url}"
end tell
return "APERTO"
'''
    return f'''
tell application "{browser}"
  activate
  if (count of windows) is 0 then
    make new window
  end if
  set URL of active tab of front window to "{url}"
end tell
return "APERTO"
'''


def current_url_script(browser: str) -> str:
    tab = "current tab" if _is_safari(browser) else "active tab"
    return f'''
tell application "{browser}"
  return URL of {tab} of front window
end tell
'''


def _js(browser: str, javascript: str) -> str:
    payload = javascript.replace("\\", "\\\\").replace('"', '\\"')
    if _is_safari(browser):
        return f'''
tell application "{browser}"
  activate
  do JavaScript "{payload}" in current tab of front window
end tell
'''
    return f'''
tell application "{browser}"
  activate
  tell active tab of front window
    execute javascript "{payload}"
  end tell
end tell
'''


def find_field_script(browser: str, selector: str) -> str:
    css = selector.replace("'", "\\'")
    return _js(
        browser,
        f"(function(){{var e=document.querySelector('{css}');return e?'TROVATO':'{JS_MISSING}';}})()",
    )


def fill_field_script(browser: str, selector: str, text: str) -> str:
    css = selector.replace("'", "\\'")
    value = json.dumps(text)[1:-1]
    return _js(
        browser,
        f"(function(){{var e=document.querySelector('{css}');if(!e)return '{JS_MISSING}';"
        f"e.focus();e.value='{value}';"
        "e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "return 'SCRITTO';})()",
    )


def open_url(runner: Runner, browser: str, url: str) -> None:
    runner.osascript(open_url_script(browser, url))


def current_url(runner: Runner, browser: str) -> str:
    try:
        return runner.osascript(current_url_script(browser))
    except MacControlError as exc:
        raise _translate(exc) from exc


def same_site(expected: str, actual: str) -> bool:
    """Vero solo se la pagina aperta è dello stesso sito del portale."""

    want = (urlparse(expected).hostname or "").lower().removeprefix("www.")
    got = (urlparse(actual).hostname or "").lower().removeprefix("www.")
    if not want or not got:
        return False
    return got == want or got.endswith("." + want)


def field_is_there(runner: Runner, browser: str, selector: str) -> bool:
    try:
        answer = runner.osascript(find_field_script(browser, selector))
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "TROVATO" in answer and JS_MISSING not in answer


def fill_field(runner: Runner, browser: str, selector: str, text: str) -> bool:
    try:
        answer = runner.osascript(fill_field_script(browser, selector, text))
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "SCRITTO" in answer


def screenshot(runner: Runner) -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        return runner.screencapture(Path(folder) / "schermo.png")


def _translate(exc: MacControlError) -> MacControlError:
    text = str(exc).lower()
    if "apple events" in text or "not allowed" in text or "-1743" in text:
        return MacControlError(
            "Il browser non accetta i comandi. In Chrome: Visualizza, Sviluppo, "
            "Consenti JavaScript dagli Apple Event. In Safari: Sviluppo, "
            "Consenti JavaScript dagli Apple Event. Poi riprova."
        )
    if "assistive" in text or "accessibility" in text or "-25211" in text:
        return MacControlError(
            "Manca il permesso Accessibilità. Impostazioni di Sistema, Privacy e "
            "sicurezza, Accessibilità: attiva Kreluna Agent. Poi riprova."
        )
    return exc
