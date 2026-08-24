import pytest
from agent.capabilities.portal import open_portal
from agent.tools import mac_browser
from kreluna_shared.agents import preferred_role
from kreluna_shared.capabilities import validate_capability_args
from kreluna_shared.planner import plan_deterministic
from kreluna_shared.programs import load_portals, load_settings, portal_for_key
from pydantic import ValidationError


class FakeMac:
    """Finto Mac: registra i comandi invece di eseguirli."""

    def __init__(
        self,
        field_after: int = 0,
        png: bytes = b"\x89PNG-finta",
        installed: tuple[str, ...] = ("Google Chrome", "Safari"),
        page_url: str | None = None,
    ):
        self.scripts: list[str] = []
        self.shots = 0
        self.field_after = field_after
        self.looks = 0
        self.png = png
        self.installed = installed
        self.page_url = page_url

    def osascript(self, script: str) -> str:
        self.scripts.append(script)
        if script.strip().startswith("id of application"):
            name = script.split('"')[1]
            if name not in self.installed:
                raise mac_browser.MacControlError(f'Application "{name}" not found (-1728)')
            return "com.example." + name.lower().replace(" ", "")
        if "return URL of" in script:
            return self.page_url or "https://www.cgn.it/area"
        if "querySelector" in script and "value=" not in script:
            self.looks += 1
            return "TROVATO" if self.looks > self.field_after else mac_browser.JS_MISSING
        if "value=" in script:
            return "SCRITTO"
        return "APERTO"

    def screencapture(self, path):
        self.shots += 1
        return self.png


def run(fake: FakeMac, **kwargs):
    naps: list[float] = []
    result = open_portal(
        runner=fake,
        supported=lambda: True,
        sleep=naps.append,
        **kwargs,
    )
    return result, naps


def test_portals_and_settings_load():
    keys = {portal.key for portal in load_portals()}
    assert {"visure-cgn", "durc-inps", "contratti-ade", "camerali-cgn", "fatture-webdesk"} <= keys
    cgn = portal_for_key("visure-cgn")
    assert cgn is not None and cgn.role == "pc-visure"
    assert "cgn" in cgn.url
    assert load_settings().mac_browser


def test_the_right_pc_gets_the_portal():
    assert preferred_role("portal_open", {"portal": "visure-cgn"}) == "pc-visure"
    assert preferred_role("portal_open", {"portal": "durc-inps"}) == "pc-durc"
    assert preferred_role("portal_open", {"portal": "inventato"}) is None


def test_opens_the_site_and_fills_the_field():
    fake = FakeMac()
    result, _ = run(fake, portal="visure-cgn", query="Bianchi Laura")
    assert result["ok"] is True
    assert result["live"] is True
    assert result["sent"] is False
    assert result["filled"] is True
    joined = " ".join(fake.scripts)
    assert "Google Chrome" in joined
    assert "cgn.it" in joined
    assert "Bianchi Laura" in joined
    assert fake.shots == 2
    assert all(shot["metadata"]["live"] for shot in result["evidence"])
    assert "non ho scaricato" in result["message"].lower()


def test_never_presses_enter_or_submits():
    fake = FakeMac()
    run(fake, portal="visure-cgn", query="Bianchi Laura")
    joined = " ".join(fake.scripts).lower()
    for forbidden in ("submit", "form.submit", "keystroke return", "key code 36", "click"):
        assert forbidden not in joined


def test_waits_for_the_human_login_then_gives_up_politely():
    fake = FakeMac(field_after=10_000)
    result, naps = run(fake, portal="durc-inps", query="Bianchi Laura")
    assert result["filled"] is False
    assert "SPID" in result["message"] or "spid" in result["message"]
    assert "di nuovo" in result["message"]
    assert naps, "deve aspettare che il titolare faccia il login"
    assert sum(naps) <= load_settings().wait_for_login_seconds


def test_second_try_after_login_fills_it():
    fake = FakeMac(field_after=2)
    result, naps = run(fake, portal="visure-cgn", query="Rossi Mario")
    assert result["filled"] is True
    assert len(naps) == 2


def test_not_a_mac_says_so_instead_of_pretending():
    with pytest.raises(RuntimeError) as err:
        open_portal(portal="visure-cgn", query="x", supported=lambda: False)
    assert "Mac" in str(err.value)


def test_unknown_portal_is_refused():
    with pytest.raises(ValueError):
        open_portal(portal="portale-finto", supported=lambda: True)


def test_it_refuses_to_type_on_the_wrong_site():
    fake = FakeMac(page_url="https://mail.google.com/mail/u/0")
    result, _ = run(fake, portal="visure-cgn", query="Bianchi Laura")
    assert result["filled"] is False
    assert "altro sito" in result["message"]
    assert "Bianchi Laura" not in " ".join(fake.scripts)
    assert result["evidence"][-1]["metadata"]["step"] == "sito-sbagliato"


def test_same_site_accepts_subdomains_and_refuses_strangers():
    assert mac_browser.same_site("https://www.cgn.it", "https://area.cgn.it/visure")
    assert mac_browser.same_site("https://www.inps.it", "https://serviziweb2.inps.it/x")
    assert not mac_browser.same_site("https://www.cgn.it", "https://cgn.it.truffa.example")
    assert not mac_browser.same_site("https://www.cgn.it", "https://www.inps.it")


def test_it_uses_safari_when_chrome_is_missing():
    fake = FakeMac(installed=("Safari",), page_url="https://www.cgn.it/visure")
    result, _ = run(fake, portal="visure-cgn", query="Rossi Mario")
    assert result["browser"] == "Safari"
    assert result["filled"] is True
    joined = " ".join(fake.scripts)
    assert "do JavaScript" in joined
    assert "execute javascript" not in joined


def test_no_browser_at_all_says_what_to_install():
    fake = FakeMac(installed=())
    with pytest.raises(mac_browser.MacControlError) as err:
        run(fake, portal="visure-cgn", query="x")
    assert "Chrome" in str(err.value)


def test_permission_errors_explain_what_to_switch_on():
    blocked = mac_browser.MacControlError("Not allowed to send Apple events to Google Chrome. (-1743)")
    assert "Apple Event" in str(mac_browser._translate(blocked))
    no_access = mac_browser.MacControlError("assistive access is not enabled (-25211)")
    assert "Accessibilità" in str(mac_browser._translate(no_access))


def test_planner_only_goes_live_when_asked():
    demo = plan_deterministic("Prepara la visura per Gadducci")
    assert demo.tasks[0].capability == "visure_prepare"

    live = plan_deterministic("Apri il sito CGN e fai la visura vera per Gadducci")
    assert live.ok
    task = live.tasks[0]
    assert task.capability == "portal_open"
    assert task.args["portal"] == "visure-cgn"
    assert task.args["query"] == "Andrea Gadducci"
    assert "login lo fai tu" in live.summary

    durc = plan_deterministic("Apri il sito INPS e prepara il DURC vero per Gadducci")
    assert durc.tasks[0].args["portal"] == "durc-inps"


def test_portal_args_are_validated():
    clean = validate_capability_args("portal_open", {"portal": "Visure-CGN", "query": "  Rossi   Mario "})
    assert clean["portal"] == "visure-cgn"
    assert clean["query"] == "Rossi Mario"
    with pytest.raises(ValidationError):
        validate_capability_args("portal_open", {"portal": "../../etc/passwd"})
