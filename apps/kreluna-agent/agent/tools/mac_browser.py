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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from agent.tools.screen_pointer import move_and_click

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
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MacControlError(
                f"Il browser non ha risposto entro {int(self.timeout)} secondi."
            ) from exc
        if result.returncode != 0:
            raise MacControlError((result.stderr or "osascript non ha risposto").strip())
        return result.stdout.strip()

    def open_application_url(self, browser: str, url: str) -> None:
        """Ripiego sicuro per aprire una pagina senza Apple Events."""

        try:
            result = subprocess.run(
                ["/usr/bin/open", "-a", browser, url],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MacControlError("Il Mac non è riuscito ad aprire il browser.") from exc
        if result.returncode != 0:
            raise MacControlError((result.stderr or "Il browser non si apre").strip())

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


LEARN_JS = (
    "(function(){var out=[];var els=document.querySelectorAll('input,select,textarea,button');"
    "for(var i=0;i<els.length&&out.length<40;i++){var e=els[i];var r=e.getBoundingClientRect();"
    "if(r.width===0||r.height===0)continue;var lab='';"
    "if(e.labels&&e.labels.length)lab=e.labels[0].innerText||'';"
    "out.push({tag:e.tagName.toLowerCase(),type:e.type||'',name:e.name||'',id:e.id||'',"
    "placeholder:e.placeholder||'',aria:e.getAttribute('aria-label')||'',"
    "label:(lab||'').trim().slice(0,60),testo:(e.innerText||'').trim().slice(0,40)});}"
    "return JSON.stringify({url:location.href,titolo:document.title,campi:out});})()"
)


def page_fields(runner: Runner, browser: str) -> dict:
    """Guarda la pagina aperta e dice quali campi ci sono, per imparare il programma."""

    try:
        answer = runner.osascript(_js(browser, LEARN_JS))
    except MacControlError as exc:
        raise _translate(exc) from exc
    start, end = answer.find("{"), answer.rfind("}")
    if start == -1 or end <= start:
        return {"url": "", "titolo": "", "campi": []}
    try:
        data = json.loads(answer[start : end + 1])
    except json.JSONDecodeError:
        return {"url": "", "titolo": "", "campi": []}
    return data if isinstance(data, dict) else {"url": "", "titolo": "", "campi": []}


def suggest_selector(field: dict) -> str:
    """Il modo più stabile per ritrovare quel campo domani."""

    tag = field.get("tag") or "input"
    for key, shape in (("id", "#{}"), ("name", '{}[name="{}"]')):
        value = (field.get(key) or "").strip()
        if not value:
            continue
        if key == "id":
            return shape.format(value)
        return shape.format(tag, value)
    placeholder = (field.get("placeholder") or "").strip()
    if placeholder:
        return f'{tag}[placeholder="{placeholder}"]'
    aria = (field.get("aria") or "").strip()
    if aria:
        return f'{tag}[aria-label="{aria}"]'
    kind = (field.get("type") or "").strip()
    return f'{tag}[type="{kind}"]' if kind else tag


def find_field_script(browser: str, selector: str) -> str:
    css = selector.replace("'", "\\'")
    return _js(
        browser,
        f"(function(){{var e=document.querySelector('{css}');return e?'TROVATO':'{JS_MISSING}';}})()",
    )


def fill_field_script(browser: str, selector: str, text: str) -> str:
    css = selector.replace("'", "\\'")
    value = json.dumps(text)
    return _js(
        browser,
        f"(function(){{var e=document.querySelector('{css}');if(!e)return '{JS_MISSING}';"
        f"e.focus();e.value={value};"
        "e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "return 'SCRITTO';})()",
    )


def field_center_script(browser: str, selector: str) -> str:
    """Centro del campo sullo schermo, ricavato dalla pagina e non dal modello."""

    css = selector.replace("'", "\\'")
    return _js(
        browser,
        f"(function(){{var e=document.querySelector('{css}');if(!e)return '{JS_MISSING}';"
        "var r=e.getBoundingClientRect();var chrome=Math.max(0,window.outerHeight-window.innerHeight);"
        "var border=Math.max(0,(window.outerWidth-window.innerWidth)/2);"
        "return JSON.stringify({x:Math.round(window.screenX+border+r.left+r.width/2),"
        "y:Math.round(window.screenY+chrome+r.top+r.height/2),"
        "screen_width:window.screen.width,screen_height:window.screen.height});})()",
    )


def open_url(runner: Runner, browser: str, url: str) -> None:
    try:
        runner.osascript(open_url_script(browser, url))
    except MacControlError:
        fallback = getattr(runner, "open_application_url", None)
        if fallback is None:
            raise
        fallback(browser, url)


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


def field_center(runner: Runner, browser: str, selector: str) -> dict[str, int] | None:
    try:
        answer = runner.osascript(field_center_script(browser, selector))
    except MacControlError as exc:
        raise _translate(exc) from exc
    start, end = answer.find("{"), answer.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(answer[start : end + 1])
        return {key: int(data[key]) for key in ("x", "y", "screen_width", "screen_height")}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def fill_field_visible(
    runner: Runner,
    browser: str,
    selector: str,
    text: str,
    *,
    mover: Callable[..., bool] = move_and_click,
) -> tuple[bool, bool]:
    """Mostra il mouse sul campo e poi scrive, senza premere Invio."""

    center = field_center(runner, browser, selector)
    moved = False
    if center:
        moved = mover(
            center["x"],
            center["y"],
            screen_width=center["screen_width"],
            screen_height=center["screen_height"],
            click=True,
        )
    return fill_field(runner, browser, selector, text), moved


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
