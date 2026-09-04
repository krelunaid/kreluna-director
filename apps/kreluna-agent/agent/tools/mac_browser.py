"""Guida il browser vero del Mac: apre, controlla l'indirizzo, scrive nel campo, fotografa.

Tre regole di questo file:
- il campo si trova nella pagina, non a coordinate del mouse;
- non si scrive niente se la pagina aperta non è quella del portale giusto;
- non si preme mai invio e non si invia mai un modulo.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from agent.tools.browser_command import DEDICATED, BrowserCommand
from agent.tools.screen_pointer import move_and_click

JS_MISSING = "NON_TROVATO"
JS_BLOCKED = "AZIONE_BLOCCATA"
CHROME_FAMILY = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium", "Vivaldi")
SAFARI = "Safari"

# Questi comandi non devono mai essere premuti da una procedura di preparazione.
# Il controllo e' anche dentro lo script JavaScript, cosi una configurazione
# corrotta non puo' aggirarlo.
FORBIDDEN_ACTION_TEXT = ("salva", "salva comunque", "emetti", "invia", "trasmetti", "paga")


class MacControlError(RuntimeError):
    """Manca un permesso sul Mac, oppure il browser non risponde."""


def screen_capture_allowed() -> bool:
    """Controlla il consenso senza far comparire ogni volta la finestra macOS."""

    if sys.platform != "darwin":
        return True
    try:
        core_graphics = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        preflight = core_graphics.CGPreflightScreenCaptureAccess
        preflight.restype = ctypes.c_bool
        return bool(preflight())
    except (AttributeError, OSError):
        return True


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
        if not screen_capture_allowed():
            raise MacControlError("Registrazione schermo non autorizzata")
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

    if getattr(runner, "dedicated", False):
        return DEDICATED
    for candidate in (preferred, *CHROME_FAMILY, SAFARI):
        if candidate and _is_installed(runner, candidate):
            return candidate
    raise MacControlError(
        "Non trovo Safari, Chrome, Edge o Brave su questo Mac."
    )


def _is_safari(browser: str) -> bool:
    return browser.strip().lower() == "safari"


SAFARI_REAL_WINDOW = '''
  set webWindow to missing value
  repeat with candidateWindow in windows
    if (count of tabs of candidateWindow) > 0 then
      set webWindow to candidateWindow
      exit repeat
    end if
  end repeat
  if webWindow is missing value then error "Nessuna finestra Safari con schede"
'''


def open_url_script(browser: str, url: str) -> str:
    if browser == DEDICATED:
        return BrowserCommand("navigate", url)
    if _is_safari(browser):
        return f'''
tell application "{browser}"
  activate
  set hasWebTabs to false
  repeat with candidateWindow in windows
    if (count of tabs of candidateWindow) > 0 then set hasWebTabs to true
  end repeat
  if not hasWebTabs then
    make new document
  end if
{SAFARI_REAL_WINDOW}
  set URL of current tab of webWindow to "{url}"
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
    if browser == DEDICATED:
        return BrowserCommand("url")
    tab = "current tab" if _is_safari(browser) else "active tab"
    setup = SAFARI_REAL_WINDOW if _is_safari(browser) else ""
    window = "webWindow" if _is_safari(browser) else "front window"
    return f'''
tell application "{browser}"
{setup}
  return URL of {tab} of {window}
end tell
'''


def _js(browser: str, javascript: str, *, read_only: bool = False) -> str:
    if browser == DEDICATED:
        return BrowserCommand("evaluate", javascript, read_only)
    payload = javascript.replace("\\", "\\\\").replace('"', '\\"')
    if _is_safari(browser):
        return f'''
tell application "{browser}"
  activate
{SAFARI_REAL_WINDOW}
  do JavaScript "{payload}" in current tab of webWindow
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
        read_only=True,
    )


def click_selector_script(browser: str, selector: str) -> str:
    # This direct activation is only authorized for Webdesk login, never invoices.
    if selector != "#submitButton":
        raise ValueError("Direct activation is limited to Webdesk login")
    css = selector.replace("'", "\\'")
    return _js(
        browser,
        "(function(){if(location.origin!=='https://app.webdesk.it'||"
        "location.pathname!=='/Apps/Login/View')return 'AZIONE_BLOCCATA';"
        f"var e=document.querySelector('{css}');if(!e)return '{JS_MISSING}';"
        "if(e.disabled||e.getAttribute('aria-disabled')==='true'||"
        "!e.getClientRects().length)return 'AZIONE_BLOCCATA';"
        "var u=document.querySelector('#loginInput'),p=document.querySelector('#passwordInput'),s=document.querySelector('#studioInput');"
        "if(!u||!p||!s||!u.value.trim()||!p.value||!s.value.trim())return 'AZIONE_BLOCCATA';"
        "e.click();return 'CLICCATO';})()",
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


def _recursive_dom_helpers() -> str:
    """JS condiviso per cercare anche negli iframe Webdesk accessibili."""

    return (
        "var docs=[];function walk(d){docs.push(d);var fs=d.querySelectorAll('iframe');"
        "for(var i=0;i<fs.length;i++){try{if(fs[i].contentDocument)walk(fs[i].contentDocument);}"
        "catch(_e){}}}walk(document);"
        "function norm(v){return (v||'').replace(/\\s+/g,' ').trim().toLowerCase();}"
        "function vis(e){if(!e)return false;var r=e.getBoundingClientRect();"
        "var s=e.ownerDocument.defaultView.getComputedStyle(e);"
        "return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}"
    )


def page_text_script(browser: str) -> str:
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + "var out=[];for(var i=0;i<docs.length;i++){out.push(docs[i].body?docs[i].body.innerText:'');}"
        "return out.join('\\n').slice(0,50000);})()",
    )


def click_text_in_section_script(browser: str, section: str, action: str, *, double: bool = False) -> str:
    section_value = json.dumps(section)
    action_value = json.dumps(action)
    forbidden = json.dumps(list(FORBIDDEN_ACTION_TEXT))
    event = "dblclick" if double else "click"
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + f"var section=norm({section_value}),action=norm({action_value}),deny={forbidden};"
        "if(deny.some(function(x){return action===x||action.indexOf(x)>=0;}))"
        f"return '{JS_BLOCKED}';"
        "var tags='button,a,[role=button],input,div,span';var candidates=[],best=99;"
        "for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll(tags);"
        "for(var j=0;j<all.length;j++){var e=all[j];if(!vis(e))continue;"
        "var own=norm(e.innerText||e.value||e.getAttribute('aria-label'));"
        "if(own!==action)continue;var p=e,ok=!section;"
        "for(var depth=0;p&&depth<8;depth++,p=p.parentElement){"
        "if(norm(p.innerText).indexOf(section)>=0){ok=true;break;}}"
        "if(ok&&depth<best){best=depth;candidates=[e];}else if(ok&&depth===best)candidates.push(e);}}"
        f"if(candidates.length!==1)return '{JS_MISSING}:'+candidates.length;"
        f"candidates[0].dispatchEvent(new MouseEvent('{event}',{{bubbles:true,cancelable:true,view:candidates[0].ownerDocument.defaultView}}));"
        "return 'CLICCATO';})()",
    )


def text_in_section_center_script(browser: str, section: str, action: str) -> str:
    """Centro visibile di un controllo testuale, anche dentro iframe annidati."""

    section_value = json.dumps(section)
    action_value = json.dumps(action)
    forbidden = json.dumps(list(FORBIDDEN_ACTION_TEXT))
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + f"var section=norm({section_value}),action=norm({action_value}),deny={forbidden};"
        "if(deny.some(function(x){return action===x||action.indexOf(x)>=0;}))"
        f"return '{JS_BLOCKED}';"
        "var tags='button,a,[role=button],input,div,span';var candidates=[],best=99;"
        "for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll(tags);"
        "for(var j=0;j<all.length;j++){var e=all[j];if(!vis(e))continue;"
        "var own=norm(e.innerText||e.value||e.getAttribute('aria-label'));"
        "if(own!==action)continue;var p=e,ok=!section;"
        "for(var depth=0;p&&depth<8;depth++,p=p.parentElement){"
        "if(norm(p.innerText).indexOf(section)>=0){ok=true;break;}}"
        "if(ok&&depth<best){best=depth;candidates=[e];}else if(ok&&depth===best)candidates.push(e);}}"
        f"if(candidates.length!==1)return '{JS_MISSING}:'+candidates.length;"
        "var e=candidates[0],r=e.getBoundingClientRect(),w=e.ownerDocument.defaultView;"
        "var left=r.left,top=r.top;"
        "while(w&&w!==w.top){try{var frame=w.frameElement;if(!frame)break;"
        "var fr=frame.getBoundingClientRect();left+=fr.left;top+=fr.top;w=w.parent;}catch(_e){break;}}"
        "var root=w||window,chrome=Math.max(0,root.outerHeight-root.innerHeight);"
        "var border=Math.max(0,(root.outerWidth-root.innerWidth)/2);"
        "return JSON.stringify({x:Math.round(root.screenX+border+left+r.width/2),"
        "y:Math.round(root.screenY+chrome+top+r.height/2),"
        "screen_width:root.screen.width,screen_height:root.screen.height});})()",
    )


def click_unique_text_match_script(browser: str, section: str, words: str) -> str:
    """Clicca l'unico suggerimento che contiene tutte le parole cercate."""

    section_value = json.dumps(section)
    words_value = json.dumps(words)
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + f"var section=norm({section_value}),tokens=norm({words_value}).split(' ').filter(Boolean),found=[];"
        "if(tokens.length<2)return 'NON_TROVATO:0';"
        "for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll('div,span,li,a,[role=option],[role=row]');"
        "for(var j=0;j<all.length;j++){var e=all[j];if(!vis(e))continue;var own=norm(e.innerText);"
        "if(!tokens.every(function(t){return own.indexOf(t)>=0;}))continue;"
        "var p=e,inside=!section;for(var depth=0;p&&depth<10;depth++,p=p.parentElement){"
        "if(norm(p.innerText).indexOf(section)>=0){inside=true;break;}}if(!inside)continue;"
        "var childMatch=false;for(var k=0;k<e.children.length;k++){var ct=norm(e.children[k].innerText);"
        "if(tokens.every(function(t){return ct.indexOf(t)>=0;})){childMatch=true;break;}}"
        "if(!childMatch)found.push(e);}}"
        f"if(found.length!==1)return '{JS_MISSING}:'+found.length;"
        "found[0].dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:found[0].ownerDocument.defaultView}));"
        "return 'CLICCATO';})()",
    )


def fill_textbox_near_label_script(browser: str, label: str, text: str) -> str:
    label_value = json.dumps(label)
    text_value = json.dumps(text)
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + f"var wanted=norm({label_value}),value={text_value},found=[];"
        "for(var i=0;i<docs.length;i++){var d=docs[i];var labels=d.querySelectorAll('label,[aria-label]');"
        "for(var j=0;j<labels.length;j++){var l=labels[j];var caption=norm(l.innerText||l.getAttribute('aria-label'));"
        "if(caption.indexOf(wanted)<0)continue;var e=null;"
        "if(l.htmlFor)e=d.getElementById(l.htmlFor);"
        "if(!e)e=l.querySelector('input,textarea');"
        "if(!e&&l.parentElement)e=l.parentElement.querySelector('input,textarea');"
        "if(!e&&l.nextElementSibling)e=l.nextElementSibling.matches('input,textarea')?l.nextElementSibling:l.nextElementSibling.querySelector('input,textarea');"
        "if(e&&vis(e)&&!e.disabled&&!e.readOnly&&found.indexOf(e)<0)found.push(e);}}"
        "if(found.length===0){for(var x=0;x<docs.length;x++){var inputs=docs[x].querySelectorAll('input[type=text],input:not([type]),textarea');"
        "for(var y=0;y<inputs.length;y++){var input=inputs[y];if(!vis(input)||input.disabled||input.readOnly)continue;"
        "var p=input.parentElement,match=false;for(var depth=0;p&&depth<5;depth++,p=p.parentElement){"
        "var caption=norm(p.innerText);if(caption===wanted||caption.indexOf(wanted+' ')===0){match=true;break;}}"
        "if(match&&found.indexOf(input)<0)found.push(input);}}}"
        f"if(found.length!==1)return '{JS_MISSING}:'+found.length;"
        "var e=found[0],w=e.ownerDocument.defaultView,proto=e.tagName==='TEXTAREA'?w.HTMLTextAreaElement.prototype:w.HTMLInputElement.prototype;"
        "var setter=Object.getOwnPropertyDescriptor(proto,'value').set;setter.call(e,value);e.focus();"
        "e.dispatchEvent(new w.InputEvent('input',{bubbles:true,inputType:'insertText',data:value.slice(-1)}));"
        "e.dispatchEvent(new w.Event('change',{bubbles:true}));return 'SCRITTO';})()",
    )


def fill_invoice_line_script(
    browser: str,
    row_index: int,
    description: str,
    quantity: float,
    unit_net_eur: float,
) -> str:
    """Compila i soli campi testuali di una riga Webdesk, senza salvarla."""

    description_value = json.dumps(description)
    quantity_value = json.dumps(f"{quantity:.2f}".replace(".", ","))
    amount_value = json.dumps(f"{unit_net_eur:.2f}".replace(".", ","))
    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + "var rows=[];for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll('tbody tr');"
        "for(var j=0;j<all.length;j++){var d=all[j].querySelector('input[placeholder*=\"Inserisci descrizione prodotto\"]');"
        "if(d&&vis(d))rows.push(all[j]);}}"
        f"if(rows.length<={row_index})return '{JS_MISSING}:RIGA';var row=rows[{row_index}],cells=row.children;"
        f"if(cells.length<12)return '{JS_MISSING}:COLONNE';"
        "function write(e,value){if(!e||e.disabled||e.readOnly)return false;var w=e.ownerDocument.defaultView;"
        "var proto=e.tagName==='TEXTAREA'?w.HTMLTextAreaElement.prototype:w.HTMLInputElement.prototype;"
        "var setter=Object.getOwnPropertyDescriptor(proto,'value').set;setter.call(e,value);e.focus();"
        "e.dispatchEvent(new w.InputEvent('input',{bubbles:true,inputType:'insertText',data:value.slice(-1)}));"
        "e.dispatchEvent(new w.Event('change',{bubbles:true}));e.dispatchEvent(new w.FocusEvent('blur',{bubbles:true}));return true;}"
        f"if(!write(cells[2].querySelector('input,textarea'),{description_value}))return '{JS_MISSING}:DESCRIZIONE';"
        f"if(!write(cells[4].querySelector('input'),{quantity_value}))return '{JS_MISSING}:QUANTITA';"
        f"if(!write(cells[6].querySelector('input'),{amount_value}))return '{JS_MISSING}:IMPORTO';"
        "return 'RIGA_SCRITTA';})()",
    )


def invoice_line_vat_center_script(browser: str, row_index: int) -> str:
    """Centro del menu IVA della riga richiesta, ricavato dal DOM reale."""

    return _js(
        browser,
        "(function(){" + _recursive_dom_helpers()
        + "var rows=[];for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll('tbody tr');"
        "for(var j=0;j<all.length;j++){var d=all[j].querySelector('input[placeholder*=\"Inserisci descrizione prodotto\"]');"
        "if(d&&vis(d))rows.push(all[j]);}}"
        f"if(rows.length<={row_index})return '{JS_MISSING}:RIGA';var cells=rows[{row_index}].children;"
        f"if(cells.length<12)return '{JS_MISSING}:COLONNE';var e=cells[8].querySelector('.hsDropDownMultiLabel')||cells[8];"
        f"if(!vis(e))return '{JS_MISSING}:IVA';var r=e.getBoundingClientRect(),w=e.ownerDocument.defaultView,left=r.left,top=r.top;"
        "while(w&&w!==w.top){try{var frame=w.frameElement;if(!frame)break;var fr=frame.getBoundingClientRect();"
        "left+=fr.left;top+=fr.top;w=w.parent;}catch(_e){break;}}var root=w||window;"
        "var chrome=Math.max(0,root.outerHeight-root.innerHeight),border=Math.max(0,(root.outerWidth-root.innerWidth)/2);"
        "return JSON.stringify({x:Math.round(root.screenX+border+left+r.width/2),"
        "y:Math.round(root.screenY+chrome+top+r.height/2),screen_width:root.screen.width,screen_height:root.screen.height});})()",
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


def page_text(runner: Runner, browser: str) -> str:
    """Testo visibile della pagina e degli iframe accessibili, senza modificarla."""

    try:
        return runner.osascript(page_text_script(browser))
    except MacControlError as exc:
        raise _translate(exc) from exc


def click_webdesk_smart(runner: Runner, browser: str) -> bool:
    """Activate the observed service tile by DOM, independent of mouse position."""
    script = _js(browser, """(function(){
      if(location.origin !== 'https://app.webdesk.it' ||
         location.pathname !== '/Apps/Dashboard/View') return 'WRONG_PAGE';
      var tiles=Array.from(document.querySelectorAll('#area_servizi .tile_servizi'));
      tiles=tiles.filter(function(e){
        var r=e.getBoundingClientRect(),s=getComputedStyle(e);
        return (e.innerText||'').trim().replace(/\\s+/g,' ').toLowerCase()==='fattura smart'
          && r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
      });
      if(tiles.length!==1) return 'AMBIGUOUS_SERVICE';
      tiles[0].click();
      return 'SMART_ACTIVATED';
    })()""")
    return runner.osascript(script) == "SMART_ACTIVATED"


def click_text_in_section(
    runner: Runner,
    browser: str,
    section: str,
    action: str,
    *,
    double: bool = False,
    mover: Callable[..., bool] = move_and_click,
) -> bool:
    """Clicca un controllo univoco col mouse visibile, mai un'azione definitiva."""

    clean = action.strip().lower()
    if any(word in clean for word in FORBIDDEN_ACTION_TEXT):
        raise RuntimeError("AZIONE_WEB_DESK_VIETATA")
    if getattr(runner, "dedicated", False):
        answer = runner.osascript(
            click_text_in_section_script(browser, section, action, double=double)
        )
        return "CLICCATO" in answer and JS_MISSING not in answer
    try:
        center_answer = runner.osascript(
            text_in_section_center_script(browser, section, action)
        )
        center = _parse_center(center_answer)
        if center:
            clicked = mover(
                center["x"],
                center["y"],
                screen_width=center["screen_width"],
                screen_height=center["screen_height"],
                click=True,
            )
            if clicked and double:
                clicked = mover(
                    center["x"],
                    center["y"],
                    screen_width=center["screen_width"],
                    screen_height=center["screen_height"],
                    click=True,
                )
            if clicked:
                return True
        answer = runner.osascript(
            click_text_in_section_script(browser, section, action, double=double)
        )
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "CLICCATO" in answer and JS_MISSING not in answer


def click_unique_text_match(
    runner: Runner,
    browser: str,
    section: str,
    words: str,
) -> bool:
    """Seleziona un suggerimento solo quando la corrispondenza e' unica."""

    try:
        answer = runner.osascript(click_unique_text_match_script(browser, section, words))
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "CLICCATO" in answer and JS_MISSING not in answer


def fill_textbox_near_label(
    runner: Runner,
    browser: str,
    label: str,
    text: str,
    *,
    sequential: bool = False,
    pause: Callable[[float], None] | None = None,
) -> bool:
    """Scrive in un campo identificato dalla sua etichetta, anche dentro iframe.

    Webdesk aggiorna i suggerimenti a ogni tasto: in quel caso inviamo prefissi
    progressivi con una piccola pausa, anziche' incollare il nome tutto insieme.
    """

    values = [text[:index] for index in range(1, len(text) + 1)] if sequential else [text]
    sleeper = pause or (lambda _seconds: None)
    for value in values:
        try:
            answer = runner.osascript(fill_textbox_near_label_script(browser, label, value))
        except MacControlError as exc:
            raise _translate(exc) from exc
        if "SCRITTO" not in answer:
            return False
        if sequential:
            sleeper(0.08)
    return True


def fill_invoice_line(
    runner: Runner,
    browser: str,
    row_index: int,
    description: str,
    quantity: float,
    unit_net_eur: float,
) -> bool:
    """Compila descrizione, quantità e importo unitario di una riga Webdesk."""

    if row_index < 0:
        return False
    try:
        answer = runner.osascript(
            fill_invoice_line_script(
                browser,
                row_index,
                description,
                quantity,
                unit_net_eur,
            )
        )
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "RIGA_SCRITTA" in answer and JS_MISSING not in answer


def click_invoice_line_vat(
    runner: Runner,
    browser: str,
    row_index: int,
    vat_text: str,
    *,
    mover: Callable[..., bool] = move_and_click,
) -> bool:
    """Apre il menu IVA della riga e sceglie un testo fiscale univoco."""

    if getattr(runner, "dedicated", False):
        # No OS coordinates: locate the current row again in the page.
        if row_index < 0:
            return False
        answer = runner.osascript(_js(browser,
            "(function(){" + _recursive_dom_helpers()
            + "var rows=[];for(var i=0;i<docs.length;i++){var all=docs[i].querySelectorAll('tbody tr');"
            "for(var j=0;j<all.length;j++){var d=all[j].querySelector('input[placeholder*=\"Inserisci descrizione prodotto\"]');"
            "if(d&&vis(d))rows.push(all[j]);}}"
            f"if(rows.length<={row_index})return 'NON_TROVATO';var cells=rows[{row_index}].children;"
            "if(cells.length<12)return 'NON_TROVATO';var e=cells[8].querySelector('.hsDropDownMultiLabel');"
            "if(!e||!vis(e)||e.disabled)return 'NON_TROVATO';e.click();return 'CLICCATO';})()"
        ))
        return answer == "CLICCATO" and click_text_in_section(
            runner, browser, "Nuova Fattura", vat_text, mover=mover
        )
    try:
        answer = runner.osascript(invoice_line_vat_center_script(browser, row_index))
    except MacControlError as exc:
        raise _translate(exc) from exc
    center = _parse_center(answer)
    if not center:
        return False
    if not mover(
        center["x"],
        center["y"],
        screen_width=center["screen_width"],
        screen_height=center["screen_height"],
        click=True,
    ):
        return False
    return click_text_in_section(
        runner,
        browser,
        "Nuova Fattura",
        vat_text,
        mover=mover,
    )


def field_center(runner: Runner, browser: str, selector: str) -> dict[str, int] | None:
    try:
        answer = runner.osascript(field_center_script(browser, selector))
    except MacControlError as exc:
        raise _translate(exc) from exc
    return _parse_center(answer)


def _parse_center(answer: str) -> dict[str, int] | None:
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
    click_pointer: bool = True,
) -> tuple[bool, bool]:
    """Mostra il mouse sul campo e poi scrive, senza premere Invio."""

    if getattr(runner, "dedicated", False):
        return fill_field(runner, browser, selector, text), False
    center = field_center(runner, browser, selector)
    moved = False
    if center:
        moved = mover(
            center["x"],
            center["y"],
            screen_width=center["screen_width"],
            screen_height=center["screen_height"],
            click=click_pointer,
        )
    return fill_field(runner, browser, selector, text), moved


def click_selector_visible(
    runner: Runner,
    browser: str,
    selector: str,
    *,
    mover: Callable[..., bool] = move_and_click,
) -> bool:
    """Locate login again at activation time; pointer movement is only visual."""

    script = click_selector_script(browser, selector)
    center = None if getattr(runner, "dedicated", False) else field_center(runner, browser, selector)
    if center:
        mover(
            center["x"],
            center["y"],
            screen_width=center["screen_width"],
            screen_height=center["screen_height"],
            click=False,
        )
    try:
        answer = runner.osascript(script)
    except MacControlError as exc:
        raise _translate(exc) from exc
    return "CLICCATO" in answer and JS_MISSING not in answer


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
