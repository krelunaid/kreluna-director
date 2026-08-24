"""Guida il browser vero del Mac: apre, cerca il campo per nome, scrive, fotografa.

Niente coordinate del mouse a caso: il campo si trova nella pagina.
Nessun invio: si scrive e si smette. L'invio resta un gesto umano.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

JS_MISSING = "NON_TROVATO"
JS_BLOCKED = "APPLE_EVENTS_SPENTI"


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


def open_url_script(browser: str, url: str) -> str:
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


def _js(browser: str, javascript: str) -> str:
    payload = javascript.replace("\\", "\\\\").replace('"', '\\"')
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


def type_with_keyboard_script(text: str) -> str:
    """Tastiera vera, per i programmi che non sono pagine web."""

    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'''
tell application "System Events"
  keystroke "{safe}"
end tell
return "DIGITATO"
'''


def open_url(runner: Runner, browser: str, url: str) -> None:
    runner.osascript(open_url_script(browser, url))


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
            "Consenti JavaScript dagli Apple Event. Poi riprova."
        )
    if "assistive" in text or "accessibility" in text or "-25211" in text:
        return MacControlError(
            "Manca il permesso Accessibilità. Impostazioni di Sistema, Privacy e "
            "sicurezza, Accessibilità: attiva Kreluna Agent. Poi riprova."
        )
    return exc
