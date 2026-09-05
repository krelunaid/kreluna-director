import subprocess

import pytest
from agent.capabilities import portal
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


def test_fatture_portal_describes_customer_search_and_create_fields():
    target = portal_for_key("fatture-webdesk")

    assert target is not None
    assert {"filter_type", "query", "result_rows", "access_button"} <= set(
        target.customer_search_fields
    )
    assert {
        "customer_type",
        "tax_code",
        "business_name",
        "legal_address",
        "recipient_code",
    } <= set(target.customer_create_fields)
    assert target.customer_create_fields["save_button"] == ""
    assert target.invoice_workflow["customer_search_mode"] == "sequential_keystrokes"
    assert target.invoice_workflow["new_invoice_frame_path"].endswith("CrudScDocument.html")
    assert target.invoice_workflow["line_table"]["columns"]["vat"] == 8
    assert target.invoice_workflow["line_table"]["columns"]["intent_declaration"] == 9
    assert target.invoice_workflow["intent_missing_text"] == "Nessuna dichiarazione presente"
    assert target.invoice_workflow["intent_is_per_line"] is True
    assert "Salva" in target.invoice_workflow["stop_before"]


def test_invoice_target_can_be_read_from_the_windows_installer_file(monkeypatch, tmp_path):
    target_file = tmp_path / "fatture.target"
    target_file.write_text("https://fatture.example.it/nuova", encoding="utf-8")
    monkeypatch.delenv("KRELUNA_FATTURE_TARGET", raising=False)
    monkeypatch.setenv("KRELUNA_FATTURE_TARGET_FILE", str(target_file))
    target = portal_for_key("fatture-webdesk")
    assert target is not None and target.configured is True
    assert target.url == "https://fatture.example.it/nuova"


def test_the_right_pc_gets_the_portal():
    assert preferred_role("portal_open", {"portal": "f24-ipsoa"}) == "pc-f24"
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
    assert "Safari" in joined
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


def test_webdesk_helpers_search_inside_iframes_and_refuse_final_actions():
    click_script = mac_browser.click_text_in_section_script(
        "Google Chrome", "Fatture", "+ Crea nuovo"
    )
    fill_script = mac_browser.fill_textbox_near_label_script(
        "Google Chrome", "Cliente", "Giorgio Tesi"
    )

    assert "contentDocument" in click_script
    assert "candidates.length!==1" in click_script
    assert "MouseEvent('click'" in click_script
    assert "contentDocument" in fill_script
    assert "InputEvent('input'" in fill_script
    assert "Giorgio Tesi" in fill_script

    center_script = mac_browser.text_in_section_center_script(
        "Google Chrome", "Fatture", "+ Crea nuovo"
    )
    assert "frameElement" in center_script
    assert "screen_width" in center_script

    fake = FakeMac()
    with pytest.raises(RuntimeError, match="AZIONE_WEB_DESK_VIETATA"):
        mac_browser.click_text_in_section(fake, "Google Chrome", "Fattura", "Salva")
    assert fake.scripts == []

    suggestion_script = mac_browser.click_unique_text_match_script(
        "Google Chrome", "Nuova Fattura", "Giorgio Tesi"
    )
    assert "tokens.every" in suggestion_script
    assert "found.length!==1" in suggestion_script


def test_webdesk_click_uses_dom_derived_visible_coordinates():
    class CenterMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if "screen_width" in script:
                return '{"x":588,"y":405,"screen_width":1920,"screen_height":1080}'
            return "APERTO"

    moves: list[tuple[int, int]] = []

    def move(x, y, **_kwargs):
        moves.append((x, y))
        return True

    fake = CenterMac()
    assert mac_browser.click_text_in_section(
        fake,
        "Google Chrome",
        "Fatture",
        "+ Crea nuovo",
        mover=move,
    )
    assert moves == [(588, 405)]
    assert "MouseEvent" not in " ".join(fake.scripts)


def test_webdesk_customer_name_is_written_one_character_at_a_time():
    class SequentialMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            return "SCRITTO"

    fake = SequentialMac()
    pauses: list[float] = []

    assert mac_browser.fill_textbox_near_label(
        fake,
        "Google Chrome",
        "Cliente",
        "Tesi",
        sequential=True,
        pause=pauses.append,
    )
    assert len(fake.scripts) == 4
    assert len(pauses) == 4
    assert "Tesi" in fake.scripts[-1]


def test_webdesk_invoice_line_uses_verified_columns_and_never_saves():
    class LineMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            return "RIGA_SCRITTA"

    fake = LineMac()
    assert mac_browser.fill_invoice_line(
        fake,
        "Google Chrome",
        0,
        "Consulenza fiscale",
        2,
        125.50,
    )
    script = fake.scripts[0]
    assert "cells[2]" in script
    assert "cells[4]" in script
    assert "cells[6]" in script
    assert "Consulenza fiscale" in script
    assert "125,50" in script
    for forbidden in ("submit()", "form.submit", "Salva comunque", "Emetti", "Invia"):
        assert forbidden not in script


def test_webdesk_vat_menu_is_clicked_from_dom_coordinates():
    class VatMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if "cells[8]" in script and "screen_width" in script:
                return '{"x":900,"y":600,"screen_width":1920,"screen_height":1080}'
            if "screen_width" in script:
                return '{"x":850,"y":650,"screen_width":1920,"screen_height":1080}'
            return "APERTO"

    moves: list[tuple[int, int]] = []

    def move(x, y, **_kwargs):
        moves.append((x, y))
        return True

    fake = VatMac()
    assert mac_browser.click_invoice_line_vat(
        fake,
        "Google Chrome",
        0,
        "10%",
        mover=move,
    )
    assert moves == [(900, 600), (850, 650)]


def test_real_webdesk_path_opens_invoice_and_selects_exact_customer():
    class WebdeskMac(FakeMac):
        def __init__(self):
            super().__init__(page_url="https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html")
            self.page_reads = 0

        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if script.strip().startswith("id of application"):
                return "com.google.chrome"
            if "return URL of" in script:
                return self.page_url or ""
            if "out.join" in script:
                self.page_reads += 1
                return "FATTURA SMART Home Fatture + Crea nuovo" if self.page_reads == 1 else "FATTURA SMART Nuova Fattura Cliente"
            if "MouseEvent" in script:
                return "CLICCATO"
            if "InputEvent" in script:
                return "SCRITTO"
            return "APERTO"

    fake = WebdeskMac()
    result = open_portal(
        portal="fatture-webdesk",
        query="SOCIETA' AGRICOLA GIORGIO TESI VIVAI S.S.",
        runner=fake,
        supported=lambda: True,
        sleep=lambda _seconds: None,
    )

    assert result["filled"] is True
    assert result["sent"] is False
    assert "selezionato" in result["message"]
    scripts = " ".join(fake.scripts)
    assert "Nuova Fattura" in scripts
    assert "SOCIETA' AGRICOLA GIORGIO TESI VIVAI S.S." in scripts
    assert "submit()" not in scripts
    assert "form.submit" not in scripts


@pytest.mark.parametrize("available_after, expected_calls", [(3, 3), (99, 10)])
def test_customer_suggestions_wait_without_repeating_success(monkeypatch, available_after, expected_calls):
    monkeypatch.setattr(mac_browser, "current_url", lambda *_args: "https://sme.genya.it/")
    pages = iter(["FATTURA SMART Home", "Nuova Fattura Cliente"])
    monkeypatch.setattr(mac_browser, "page_text", lambda *_args: next(pages))
    monkeypatch.setattr(mac_browser, "click_text_in_section", lambda *_args: True)
    monkeypatch.setattr(mac_browser, "fill_textbox_near_label", lambda *_args, **_kwargs: True)
    calls = []

    def select(*_args):
        calls.append(True)
        return len(calls) >= available_after

    monkeypatch.setattr(mac_browser, "click_unique_text_match", select)
    result = portal._start_webdesk_invoice(
        run=FakeMac(), browser="Safari", client_name="Cliente Prova", invoice=None,
        settings=load_settings(), sleep=lambda _: None, check=lambda: None,
        stop=lambda stage, message, **kwargs: {"stage": stage, **kwargs},
    )
    assert len(calls) == expected_calls
    assert result["stage"] == (
        "cliente-fattura-selezionato" if available_after <= 10 else "cliente-non-univoco"
    )


def test_real_webdesk_invoice_fills_multiple_vat_rows_without_saving(monkeypatch):
    fake = FakeMac(
        page_url="https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html"
    )
    page_reads = iter(
        [
            "FATTURA SMART Home Fatture + Crea nuovo\nMittente\nAzienda Prova SRL\nDestinatario",
            "FATTURA SMART Nuova Fattura Cliente Righe documento",
        ]
    )
    actions: list[tuple[str, str]] = []
    rows: list[tuple[int, str, float, float]] = []
    vats: list[tuple[int, str]] = []

    monkeypatch.setattr(mac_browser, "page_text", lambda *_args: next(page_reads))
    monkeypatch.setattr(
        mac_browser,
        "click_text_in_section",
        lambda _run, _browser, section, action, **_kwargs: actions.append((section, action)) or True,
    )
    monkeypatch.setattr(mac_browser, "fill_textbox_near_label", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mac_browser, "click_unique_text_match", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        mac_browser,
        "fill_invoice_line",
        lambda _run, _browser, index, description, quantity, amount: rows.append(
            (index, description, quantity, amount)
        ) or True,
    )
    monkeypatch.setattr(
        mac_browser,
        "click_invoice_line_vat",
        lambda _run, _browser, index, vat: vats.append((index, vat)) or True,
    )

    result = open_portal(
        portal="fatture-webdesk",
        query="Cliente Prova SRL",
        invoice={
            "client_name": "Cliente Prova SRL",
            "description": "Consulenza · Materiale",
            "account_name": "Azienda Prova SRL",
            "net_eur": 300,
            "vat_rate": 0.22,
            "lines": [
                {"description": "Consulenza", "quantity": 1, "unit_net_eur": 100, "vat_rate": 0.22},
                {"description": "Materiale", "quantity": 2, "unit_net_eur": 100, "vat_rate": 0.10},
            ],
        },
        runner=fake,
        supported=lambda: True,
        sleep=lambda _seconds: None,
    )

    assert result["filled"] is True
    assert result["sent"] is False
    assert rows == [(0, "Consulenza", 1.0, 100.0), (1, "Materiale", 2.0, 100.0)]
    assert vats == [(1, "10%")]
    assert ("Righe documento", "Aggiungi nuova riga") in actions
    assert all(action not in {"Salva", "Emetti", "Invia"} for _, action in actions)


@pytest.mark.parametrize("account,page,vat,step", [
    ("", "Azienda Prova", "standard", "emittente-da-verificare"),
    ("Altra Azienda", "Azienda Prova", "standard", "emittente-da-verificare"),
    ("Azienda Prova", "Azienda Prova", "intent_declaration", "dichiarazione-intento-da-verificare"),
])
def test_invoice_preconditions_stop_before_document_clicks(monkeypatch, account, page, vat, step):
    fake = FakeMac(page_url="https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html")
    monkeypatch.setattr(mac_browser, "page_text", lambda *_: f"FATTURA SMART\nMittente\n{page}\nDestinatario")
    def forbidden(*args, **kwargs):
        pytest.fail("Document must not be opened or edited before prerequisites")
    monkeypatch.setattr(mac_browser, "click_text_in_section", forbidden)
    monkeypatch.setattr(mac_browser, "fill_invoice_line", forbidden)
    monkeypatch.setattr(mac_browser, "click_invoice_line_vat", forbidden)
    result = open_portal("fatture-webdesk", query="Cliente Prova", invoice={
        "account_name": account, "vat_treatment": vat,
        "lines": [{"description": "Lavoro", "unit_net_eur": 100}],
    }, runner=fake, supported=lambda: True, sleep=lambda _: None)
    assert result["ok"] is False
    assert result["outcome"] == "blocked"
    assert result["step"] == step
    assert result["filled"] is False
    if step == "emittente-da-verificare" and account:
        assert account in result["message"] and page in result["message"]
        assert "Non serve riconfigurare Gmail" in result["message"]
    elif not account:
        assert "Da quale azienda" in result["message"]


def test_explicit_invoice_parties_before_amount_are_not_reversed():
    from kreluna_shared.planner import _invoice_parties
    account, client = _invoice_parties("mi prepari una fattura per Azienda Alfa al cliente Cliente Beta, di 30000 euro")
    assert account.casefold() == "azienda alfa"
    assert client.casefold() == "cliente beta"


def test_webdesk_does_not_overwrite_an_open_customer_editor():
    class BusyWebdeskMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if script.strip().startswith("id of application"):
                return "com.google.chrome"
            if "return URL of" in script:
                return "https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html"
            if "out.join" in script:
                return "FATTURA SMART Modifica cliente Salva comunque"
            return "APERTO"

    fake = BusyWebdeskMac()
    result = open_portal(
        portal="fatture-webdesk",
        query="Giorgio Tesi",
        runner=fake,
        supported=lambda: True,
        sleep=lambda _seconds: None,
    )

    assert result["filled"] is False
    assert result["sent"] is False
    assert "sovrascrivo" in result["message"]
    assert "MouseEvent" not in " ".join(fake.scripts)


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


def test_invoice_portal_uses_the_real_webdesk_login_without_submitting():
    fake = FakeMac(page_url="https://app.webdesk.it/Apps/Login/View")
    result, _ = run(fake, portal="fatture-webdesk")

    assert result["url"] == "https://app.webdesk.it/Apps/Login/View"
    assert result["sent"] is False
    assert result["filled"] is False
    assert "submit()" not in " ".join(fake.scripts).lower()


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


def test_old_demo_requests_are_routed_to_real_webdesk(monkeypatch):
    captured = {}

    def fake_open_portal(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "sent": False}

    monkeypatch.setattr(portal, "open_portal", fake_open_portal)
    result = portal.open_legacy_invoice_in_webdesk(
        client_name="Cliente Prova",
        description="Consulenza",
        net_eur=100,
        vat_rate=0.22,
    )

    assert result["sent"] is False
    assert captured["portal"] == "fatture-webdesk"
    assert captured["query"] == "Cliente Prova"
    assert captured["invoice"]["lines"] == [
        {
            "description": "Consulenza",
            "quantity": 1,
            "unit_net_eur": 100,
            "vat_rate": 0.22,
        }
    ]


def test_osascript_timeout_never_exposes_the_raw_command(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["osascript"], timeout=30)

    monkeypatch.setattr(mac_browser.subprocess, "run", timeout)
    with pytest.raises(mac_browser.MacControlError) as error:
        mac_browser.Runner().osascript("tell application \"Google Chrome\"")

    assert "30 secondi" in str(error.value)
    assert "Command" not in str(error.value)
    assert "tell application" not in str(error.value)


def test_browser_open_uses_the_safe_fallback_after_apple_event_failure():
    class FallbackMac(FakeMac):
        def __init__(self):
            super().__init__()
            self.opened: list[tuple[str, str]] = []

        def osascript(self, script: str) -> str:
            if "set URL of" in script:
                raise mac_browser.MacControlError("Il browser non ha risposto")
            return super().osascript(script)

        def open_application_url(self, browser: str, url: str) -> None:
            self.opened.append((browser, url))

    fake = FallbackMac()
    mac_browser.open_url(fake, "Google Chrome", "https://www.cgn.it")

    assert fake.opened == [("Google Chrome", "https://www.cgn.it")]


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

    invoice = plan_deterministic(
        "Prepara una fattura vera a Giorgio Tesi per 500 euro di consulenza IVA 10%"
    )
    assert invoice.tasks[0].capability == "portal_open"
    assert invoice.tasks[0].args["portal"] == "fatture-webdesk"
    assert invoice.tasks[0].args["invoice"]["lines"][0]["vat_rate"] == 0.10
    assert invoice.tasks[0].args["invoice"]["net_eur"] == 500

    durc = plan_deterministic("Apri il sito INPS e prepara il DURC vero per Gadducci")
    assert durc.tasks[0].args["portal"] == "durc-inps"


def test_portal_args_are_validated():
    clean = validate_capability_args("portal_open", {"portal": "Visure-CGN", "query": "  Rossi   Mario "})
    assert clean["portal"] == "visure-cgn"
    assert clean["query"] == "Rossi Mario"
    invoice = validate_capability_args(
        "portal_open",
        {
            "portal": "fatture-webdesk",
            "query": "Cliente Prova SRL",
            "invoice": {
                "client_name": "Cliente Prova SRL",
                "description": "Consulenza",
                "net_eur": 100,
                "lines": [{"description": "Consulenza", "unit_net_eur": 100}],
            },
        },
    )
    assert invoice["invoice"]["lines"][0]["unit_net_eur"] == 100
    with pytest.raises(ValidationError):
        validate_capability_args("portal_open", {"portal": "../../etc/passwd"})


def test_saved_access_is_filled_once_without_login_click_or_final_screenshot(monkeypatch):
    class Response:
        is_success = True

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def post(url, *args, **kwargs):
        if url.endswith("/agent/portal-location"):
            return Response({"portal_url": "https://area.cgn.example.it/login"})
        return Response(
            {
                "username": "cliente@example.it",
                "secret": "Sicura'123",
                "secret_kind": "password",
            }
        )

    monkeypatch.setattr("agent.capabilities.portal.httpx.post", post)
    fake = FakeMac(page_url="https://area.cgn.example.it/login")
    result, _ = run(
        fake,
        portal="visure-cgn",
        query="Andrea Gadducci",
        use_saved_access=True,
        director_url="https://director.example.it",
        device_id="device-1",
        task_id="task-1",
        sign_request=lambda _path, payload: {
            **payload,
            "nonce": "a" * 32,
            "sent_at": 1,
            "signature": "firma",
        },
    )

    assert result["filled"] is True
    assert "clicca tu" in result["message"].lower()
    joined = " ".join(fake.scripts)
    assert "https://area.cgn.example.it/login" in joined
    assert "cliente@example.it" in joined
    assert "Sicura'123" in joined
    assert "submit" not in joined.lower()
    assert "click" not in joined.lower()
    assert fake.shots == 1, "dopo aver compilato l'accesso non crea una schermata"


def test_webdesk_saved_access_logs_in_and_continues_invoice(monkeypatch):
    class Response:
        is_success = True

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def post(url, *args, **kwargs):
        if url.endswith("/agent/portal-location"):
            return Response(
                {
                    "portal_url": (
                        "https://sme.genya.it/Elements/Factory/Screens/"
                        "MainSmartInvoice/MainSmartInvoice.html"
                    )
                }
            )
        return Response(
                {
                    "username": "utente",
                    "secret": "segreto",
                    "credential_label": "principale",
                    "portal_account": "ABC123",
                }
        )

    logged_in = False

    def field_is_there(_run, _browser, selector):
        return not logged_in and selector in {"#loginInput", "#passwordInput"}

    def click_login(*_args, **_kwargs):
        nonlocal logged_in
        logged_in = True
        fake.page_url = "https://app.webdesk.it/Apps/Dashboard/View"
        return True

    monkeypatch.setattr("agent.capabilities.portal.httpx.post", post)
    monkeypatch.setattr(portal.mac_browser, "field_is_there", field_is_there)
    filled: list[tuple[str, str]] = []

    def fill_field(_run, _browser, selector, value):
        filled.append((selector, value))
        return True

    monkeypatch.setattr(portal.mac_browser, "fill_field", fill_field)
    monkeypatch.setattr(portal.mac_browser, "page_text", lambda *_args: "Entra in webdesk")
    monkeypatch.setattr(portal.mac_browser, "click_selector_visible", click_login)
    def click_smart(_run, _browser):
        fake.page_url = "https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html"
        return True

    monkeypatch.setattr(portal.mac_browser, "click_webdesk_smart", click_smart)
    monkeypatch.setattr(
        portal,
        "_start_webdesk_invoice",
        lambda **_kwargs: {"ok": True, "continued": True, "sent": False},
    )
    fake = FakeMac(page_url="https://app.webdesk.it/Apps/Login/View")
    result, _ = run(
        fake,
        portal="fatture-webdesk",
        query="Cliente Prova SRL",
        invoice={"client_name": "Cliente Prova SRL", "lines": []},
        use_saved_access=True,
        director_url="https://director.example.it",
        device_id="device-1",
        task_id="task-1",
        sign_request=lambda _path, payload: payload,
    )

    assert result["continued"] is True
    assert result["sent"] is False
    assert any(
        "https://app.webdesk.it/Apps/Login/View" in script for script in fake.scripts
    )
    assert filled == [
        ("#studioInput", "ABC123"),
        ("#loginInput", "utente"),
        ("#passwordInput", "segreto"),
    ]


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


def test_login_field_can_move_without_clicking_password_manager():
    class LoginMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if "screen_width" in script:
                return '{"x":500,"y":400,"screen_width":1920,"screen_height":1080}'
            if "value=" in script:
                return "SCRITTO"
            return "APERTO"

    clicks: list[bool] = []

    def move(_x, _y, **kwargs):
        clicks.append(kwargs["click"])
        return True

    written, moved = mac_browser.fill_field_visible(
        LoginMac(),
        "Safari",
        "#passwordInput",
        "segreto",
        mover=move,
        click_pointer=False,
    )

    assert written is True
    assert moved is True
    assert clicks == [False]


def test_webdesk_login_button_moves_then_uses_exact_dom_button():
    class ButtonMac(FakeMac):
        def osascript(self, script: str) -> str:
            self.scripts.append(script)
            if "screen_width" in script:
                return '{"x":600,"y":500,"screen_width":1920,"screen_height":1080}'
            if "e.click()" in script:
                return "CLICCATO"
            return "APERTO"

    physical_clicks: list[bool] = []

    def move(_x, _y, **kwargs):
        physical_clicks.append(kwargs["click"])
        return True

    fake = ButtonMac()
    assert mac_browser.click_selector_visible(
        fake, "Safari", "#submitButton", mover=move
    )
    assert physical_clicks == [False]
    assert any("#submitButton" in script and "e.click()" in script for script in fake.scripts)


def test_login_activation_does_not_depend_on_pointer(monkeypatch):
    for center in (None, {"x": 600, "y": 500, "screen_width": 1920, "screen_height": 1080}):
        monkeypatch.setattr(mac_browser, "field_center", lambda *_args: center)

        class LoginMac(FakeMac):
            def osascript(self, script):
                self.scripts.append(script)
                return "CLICCATO"

        fake = LoginMac()
        assert mac_browser.click_selector_visible(
            fake, "Safari", "#submitButton", mover=lambda *_args, **_kwargs: False
        )
        assert len(fake.scripts) == 1  # no duplicate login attempts
        assert "document.querySelector" in fake.scripts[0]


def test_direct_click_is_limited_to_visible_webdesk_login():
    script = mac_browser.click_selector_script("Safari", "#submitButton")
    assert "https://app.webdesk.it" in script
    assert "/Apps/Login/View" in script
    assert "e.disabled" in script
    assert "getClientRects" in script
    assert "#loginInput" in script and "#passwordInput" in script and "#studioInput" in script
    assert "!u.value.trim()||!p.value||!s.value.trim()" in script
    try:
        mac_browser.click_selector_script("Safari", "#saveInvoice")
    except ValueError:
        pass
    else:
        raise AssertionError("Invoice buttons must not be directly activated")


def test_safari_open_creates_document_when_only_tabless_windows_exist():
    script = mac_browser.open_url_script("Safari", "https://app.webdesk.it/Apps/Login/View")
    assert "set hasWebTabs to false" in script
    assert "count of tabs of candidateWindow" in script
    assert "if not hasWebTabs then" in script
    assert script.index("make new document") < script.index("Nessuna finestra Safari con schede")


def test_planner_uses_vault_only_when_explicitly_requested() -> None:
    ordinary = plan_deterministic("Apri il sito CGN e fai la visura vera per Gadducci")
    assert ordinary.tasks[0].args["use_saved_access"] is False
    vault = plan_deterministic(
        "Apri il sito CGN e fai la visura vera per Gadducci usando l'accesso salvato"
    )
    assert vault.tasks[0].args["use_saved_access"] is True
    assert "prima del login" in vault.summary
