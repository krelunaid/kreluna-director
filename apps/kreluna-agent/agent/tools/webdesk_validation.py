"""Only the observed Webdesk workstation-validation page; never fiscal actions."""
import json
import re

from agent.tools import mac_browser

GUARD = """
if(!['https://www.webdesk.it','https://webdesk.it'].includes(location.origin)||
location.pathname!=='/Account/AccessNewLocation.aspx')return JSON.stringify({stage:'other'});
var text=document.body.innerText.replace(/\\s+/g,' ').trim();
if(!text.includes('Validazione della postazione'))return JSON.stringify({stage:'unknown'});
var link=document.getElementById('MainContent_VaiWebdesLink');
if(/La tua postazione è stata correttament[ae] validata/.test(text)&&link&&link.getClientRects().length&&
 link.innerText.trim()==='Accedi a webdesk'&&
 link.getAttribute('href')===\"javascript:__doPostBack('ctl00$MainContent$VaiWebdesLink','')\"){
 if(action==='continue')link.click();
 return JSON.stringify({stage:'validated',acted:action==='continue'});
}
if(action==='continue')return JSON.stringify({stage:'changed'});
var emails=Array.from(new Set(text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/g)||[]));
if(emails.length!==1)return JSON.stringify({stage:'unknown'});
var recipient=emails[0].toLowerCase();
function rendered(e){return e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';}
function visible(e){return rendered(e)&&!e.disabled;}
var requestButtons=Array.from(document.querySelectorAll('button,input[type=submit],input[type=button]')).filter(
 e=>visible(e)&&(e.value||e.innerText||'').trim().toLowerCase()==='invia codice di sicurezza');
var field=document.getElementById('MainContent_CodSicurezza');
var confirm=document.getElementById('MainContent_ChangePasswordPushButton');
var stage=visible(field)&&rendered(confirm)&&(confirm.value||confirm.innerText||'').trim().toLowerCase()==='procedi'
 ?'code':requestButtons.length===1?'request':'unknown';
"""


def script(browser, action="inspect", recipient="", code=""):
    if action not in {"inspect", "request", "submit", "continue"}:
        raise ValueError("Unsupported validation action")
    if action == "submit" and not re.fullmatch(r"[A-Za-z0-9]{6}", code):
        raise ValueError("Invalid validation code")
    js = "(function(){var action=" + json.dumps(action) + ";" + GUARD
    if action != "inspect":
        js += f"if(recipient!=={json.dumps(recipient)})return JSON.stringify({{stage:'changed'}});"
    if action == "request":
        js += "if(stage!=='request')return JSON.stringify({stage:'changed'});requestButtons[0].click();"
    elif action == "submit":
        js += "if(stage!=='code')return JSON.stringify({stage:'changed'});"
        js += f"field.value={json.dumps(code)};"
        js += "field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));"
        js += "if(!visible(confirm))return JSON.stringify({stage:'changed'});confirm.click();"
    js += "return JSON.stringify({stage:stage,recipient:recipient,acted:" + ("false" if action == "inspect" else "true") + "});})()"
    if browser == "Safari":
        # Validation opens in another window. Never use the first/front window:
        # it can be the login form or an unrelated site. Refuse ambiguous tabs.
        payload = js.replace("\\", "\\\\").replace('"', '\\"')
        return '''
tell application "Safari"
  set matches to {}
  repeat with candidateWindow in windows
    if (count of tabs of candidateWindow) > 0 then
      repeat with candidateTab in tabs of candidateWindow
        set candidateURL to URL of candidateTab
        repeat with baseURL in {"https://webdesk.it/Account/AccessNewLocation.aspx", "https://www.webdesk.it/Account/AccessNewLocation.aspx"}
          if candidateURL is (baseURL as text) or candidateURL starts with ((baseURL as text) & "?") or candidateURL starts with ((baseURL as text) & "#") then
            set end of matches to contents of candidateTab
          end if
        end repeat
      end repeat
    end if
  end repeat
  if (count of matches) is not 1 then return "{\\"stage\\":\\"unknown\\"}"
  set validationTab to item 1 of matches
  return do JavaScript "''' + payload + '''" in validationTab
end tell
'''
    return mac_browser._js(browser, js, read_only=action == "inspect")


def perform(runner, browser, action="inspect", recipient="", code=""):
    try:
        result = json.loads(runner.osascript(script(browser, action, recipient, code)))
        return result if isinstance(result, dict) else {"stage": "unknown"}
    except (mac_browser.MacControlError, ValueError, TypeError):
        # Never propagate an osascript error containing the code-bearing script.
        return {"stage": "unknown"}
