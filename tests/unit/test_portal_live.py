import pytest
from agent.capabilities.portal import open_portal, prepare_invoice_portal
from agent.tools import mac_browser
from kreluna_shared.agents import preferred_role
from kreluna_shared.capabilities import validate_capability_args
from kreluna_shared.planner import plan_deterministic
from kreluna_shared.programs import Portal, load_portals, load_settings, portal_for_key
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


def test_invoice_target_can_be_overridden_without_editing_code(monkeypatch):
    monkeypatch.setenv("KRELUNA_FATTURE_TARGET", "https://fatture.example.it/nuova")
    target = portal_for_key("fatture-webdesk")
    assert target is not None
    assert target.configured is True
    assert target.url == "https://fatture.example.it/nuova"


def test_invoice_target_can_be_read_from_the_windows_installer_file(monkeypatch, tmp_path):
    target_file = tmp_path / "fatture.target"
    target_file.write_text("https://fatture.example.it/nuova", encoding="utf-8")
    monkeypatch.delenv("KRELUNA_FATTURE_TARGET", raising=False)
    monkeypatch.setenv("KRELUNA_FATTURE_TARGET_FILE", str(target_file))
    target = portal_for_key("fatture-webdesk")
    assert target is not None and target.configured is True
    assert target.url == "https://fatture.example.it/nuova"


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


def test_windows_agent_opens_the_portal_without_submitting(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("agent.capabilities.portal.sys.platform", "win32")
    monkeypatch.setattr("agent.capabilities.portal.webbrowser.open", opened.append)

    result = open_portal(portal="visure-cgn", query="Bianchi", supported=lambda: False)

    assert opened == ["https://www.cgn.it"]
    assert result["browser"] == "predefinito Windows"
    assert result["filled"] is False
    assert result["sent"] is False


def test_unknown_portal_is_refused():
    with pytest.raises(ValueError):
        open_portal(portal="portale-finto", supported=lambda: True)


def test_unconfigured_invoice_placeholder_is_never_opened():
    with pytest.raises(RuntimeError, match="percorso non configurato"):
        open_portal(portal="fatture-webdesk", supported=lambda: True)


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


def test_saved_access_is_filled_once_without_login_click_or_final_screenshot(monkeypatch):
    class Response:
        is_success = True

        @staticmethod
        def json():
            return {"username": "cliente@example.it", "secret": "Sicura'123", "secret_kind": "password"}

    monkeypatch.setattr("agent.capabilities.portal.httpx.post", lambda *args, **kwargs: Response())
    fake = FakeMac(page_url="https://www.cgn.it/login")
    result, _ = run(
        fake,
        portal="visure-cgn",
        query="Andrea Gadducci",
        use_saved_access=True,
        director_url="https://director.example.it",
        device_id="device-1",
        task_id="task-1",
        signature="firma",
    )

    assert result["filled"] is True
    assert "clicca tu" in result["message"].lower()
    joined = " ".join(fake.scripts)
    assert "cliente@example.it" in joined
    assert "Sicura'123" in joined
    assert "submit" not in joined.lower()
    assert "click" not in joined.lower()
    assert fake.shots == 1, "dopo aver compilato l'accesso non crea una schermata"


def test_secret_text_is_embedded_as_json_not_javascript_quote() -> None:
    script = mac_browser.fill_field_script("Google Chrome", "input[type=password]", "a';alert(1)//")

    assert "e.value='" not in script
    assert "alert(1)" in script


def test_invoice_form_moves_mouse_fills_known_fields_and_never_submits(monkeypatch):
    spec = Portal(
        key="fatture-webdesk",
        role="pc-fatture",
        name="Fatture prova",
        url="https://fatture.example.it/nuova",
        field="#cliente",
        login_note="Login manuale",
        configured=True,
        invoice_fields={
            "client_name": "#cliente",
            "description": "#prestazione",
            "net_eur": "#imponibile",
        },
    )
    monkeypatch.setattr("agent.capabilities.portal.portal_for_key", lambda _key: spec)

    class InvoiceMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if script.strip().startswith("id of application"):
                return "com.google.chrome"
            if "return URL of" in script:
                return "https://fatture.example.it/nuova"
            if "screen_width" in script:
                return '{"x":500,"y":400,"screen_width":1920,"screen_height":1080}'
            if "value=" in script:
                return "SCRITTO"
            if "querySelector" in script:
                return "TROVATO"
            return "APERTO"

    fake = InvoiceMac(page_url=spec.url)
    moves: list[tuple[int, int]] = []

    def move(x, y, **_kwargs):
        moves.append((x, y))
        return True

    result = prepare_invoice_portal(
        client_name="Andrea Gadducci",
        description="Manodopera",
        net_eur=5000,
        runner=fake,
        supported=lambda: True,
        sleep=lambda _seconds: None,
        mover=move,
    )

    assert result["filled"] is True
    assert result["sent"] is False
    assert result["mouse_visible"] is True
    assert len(moves) == 3
    joined = " ".join(fake.scripts).lower()
    assert "andrea gadducci" in joined
    assert "manodopera" in joined
    assert "submit()" not in joined
    assert "form.submit" not in joined


def test_planner_uses_vault_only_when_explicitly_requested() -> None:
    ordinary = plan_deterministic("Apri il sito CGN e fai la visura vera per Gadducci")
    assert ordinary.tasks[0].args["use_saved_access"] is False
    vault = plan_deterministic(
        "Apri il sito CGN e fai la visura vera per Gadducci usando l'accesso salvato"
    )
    assert vault.tasks[0].args["use_saved_access"] is True
    assert "prima del login" in vault.summary
