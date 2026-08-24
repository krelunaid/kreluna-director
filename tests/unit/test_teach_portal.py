import json

from agent.capabilities.portal import learn_portal
from agent.tools import mac_browser
from kreluna_shared.agents import preferred_role
from kreluna_shared.planner import plan_deterministic

PAGINA = {
    "url": "https://www.cgn.it/visure/ricerca",
    "titolo": "CGN - Ricerca impresa",
    "campi": [
        {"tag": "input", "type": "text", "name": "denominazione", "id": "", "placeholder": "Ragione sociale",
         "aria": "", "label": "Impresa", "testo": ""},
        {"tag": "input", "type": "text", "name": "", "id": "codiceFiscale", "placeholder": "",
         "aria": "", "label": "Codice fiscale", "testo": ""},
        {"tag": "select", "type": "", "name": "tipoVisura", "id": "", "placeholder": "",
         "aria": "Tipo di visura", "label": "", "testo": ""},
        {"tag": "button", "type": "submit", "name": "", "id": "", "placeholder": "",
         "aria": "", "label": "", "testo": "Cerca"},
    ],
}


class FakeMac:
    def __init__(self, page=None):
        self.scripts: list[str] = []
        self.page = PAGINA if page is None else page

    def osascript(self, script: str) -> str:
        self.scripts.append(script)
        if script.strip().startswith("id of application"):
            return "com.google.chrome"
        if "querySelectorAll" in script:
            return json.dumps(self.page)
        return "APERTO"

    def screencapture(self, path):
        return b"\x89PNG-finta"


def test_it_reads_the_fields_of_the_page_it_is_shown():
    fake = FakeMac()
    result = learn_portal("visure-cgn", runner=fake, supported=lambda: True)

    assert result["ok"] is True
    assert result["sent"] is False
    assert result["pagina"] == "https://www.cgn.it/visure/ricerca"
    assert result["titolo"] == "CGN - Ricerca impresa"
    nomi = [c["nome"] for c in result["campi"]]
    assert "Impresa" in nomi
    assert "Codice fiscale" in nomi
    selettori = [c["selettore"] for c in result["campi"]]
    assert 'input[name="denominazione"]' in selettori
    assert "#codiceFiscale" in selettori
    assert 'select[name="tipoVisura"]' in selettori
    assert result["bottoni"][0]["nome"] == "Cerca"


def test_it_never_writes_or_clicks_while_learning():
    fake = FakeMac()
    learn_portal("visure-cgn", runner=fake, supported=lambda: True)
    joined = " ".join(fake.scripts).lower()
    for forbidden in ("value=", "submit()", "keystroke", ".click("):
        assert forbidden not in joined


def test_a_page_without_fields_does_not_explode():
    fake = FakeMac(page={"url": "https://www.cgn.it", "titolo": "Home", "campi": []})
    result = learn_portal("visure-cgn", runner=fake, supported=lambda: True)
    assert result["campi_trovati"] == 0
    assert result["campi"] == []


def test_the_selector_prefers_the_most_stable_handle():
    assert mac_browser.suggest_selector({"tag": "input", "id": "cf", "name": "x"}) == "#cf"
    assert mac_browser.suggest_selector({"tag": "input", "name": "x"}) == 'input[name="x"]'
    assert (
        mac_browser.suggest_selector({"tag": "input", "placeholder": "Ragione sociale"})
        == 'input[placeholder="Ragione sociale"]'
    )
    assert mac_browser.suggest_selector({"tag": "input", "aria": "Cerca"}) == 'input[aria-label="Cerca"]'
    assert mac_browser.suggest_selector({"tag": "input", "type": "search"}) == 'input[type="search"]'


def test_every_pc_that_opens_a_portal_can_also_learn_it():
    from kreluna_shared.agents import capabilities_for_role, load_live_agent_roles

    for role in load_live_agent_roles():
        caps = capabilities_for_role(role.role)
        if "portal_open" in caps:
            assert "portal_learn" in caps, f"{role.role} apre il portale ma non sa impararlo"


def test_asking_to_learn_is_not_asking_to_fill():
    teach = plan_deterministic("Impara la pagina di Webdesk per le fatture")
    assert teach.ok
    assert teach.tasks[0].capability == "portal_learn"
    assert teach.tasks[0].args["portal"] == "fatture-webdesk"
    assert "non clicco niente" in teach.summary

    work = plan_deterministic("Apri il sito CGN e fai la visura vera per Gadducci")
    assert work.tasks[0].capability == "portal_open"

    assert preferred_role("portal_learn", {"portal": "fatture-webdesk"}) == "pc-fatture"
