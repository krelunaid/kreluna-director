"""Opt-in real Chromium check using intercepted fixtures, no external account."""

import os

import pytest
from agent.tools import mac_browser
from agent.tools.browser_command import DEDICATED
from agent.tools.dedicated_browser import DedicatedRunner

pytestmark = pytest.mark.skipif(
    os.environ.get("KRELUNA_TEST_BROWSER") != "1", reason="requires installed Chromium"
)


def test_real_browser_fill_click_and_separate_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, chromium_sandbox=True)
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body="""
            <label for="password">Password</label><input id="password" type="password">
            <button id="submitButton" onclick="document.querySelector('#result').textContent='accesso simulato'">Accedi</button>
            <p id="result">in attesa</p><button onclick="window.saved=true">Salva</button>
        """))
        try:
            personal = context.new_page()
            personal.goto("https://example.test/personal")
            page = context.new_page()
            runner = DedicatedRunner(page)
            mac_browser.open_url(runner, DEDICATED, "https://app.webdesk.it/Apps/Login/View")
            assert mac_browser.field_is_there(runner, DEDICATED, "#password")
            def no_pointer(*args, **kwargs):
                pytest.fail("The OS pointer must not be touched")
            assert mac_browser.fill_field_visible(runner, DEDICATED, "#password", "fixture-only", mover=no_pointer) == (True, False)
            # Switch tabs and move the browser-internal mouse to a different point.
            personal.bring_to_front()
            personal.mouse.move(300, 300)
            assert mac_browser.click_selector_visible(runner, DEDICATED, "#submitButton", mover=no_pointer)
            assert page.locator("#result").inner_text() == "accesso simulato"
            assert personal.locator("#result").inner_text() == "in attesa"
            assert personal.locator("#password").input_value() == ""
            assert page.evaluate("window.saved || false") is False
            assert personal.url == "https://example.test/personal"
            with pytest.raises(RuntimeError):
                mac_browser.click_text_in_section(runner, DEDICATED, "", "Salva", mover=no_pointer)
            page.goto("https://example.test/replaced")
            with pytest.raises(mac_browser.MacControlError):
                mac_browser.fill_field_visible(runner, DEDICATED, "#password", "fixture-only", mover=no_pointer)
            assert page.locator("#password").input_value() == ""
        finally:
            browser.close()


def test_disabled_validation_button_detected_but_not_forced():
    from agent.tools import webdesk_validation
    from playwright.sync_api import sync_playwright

    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, chromium_sandbox=True)
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body="""
          <h1>Validazione della postazione</h1><p>test@example.test</p>
          <input id="MainContent_CodSicurezza">
          <input id="MainContent_ChangePasswordPushButton" type="button" value="Procedi" disabled
                 onclick="window.submitted=true">
          <input id="MainContent_chkAccess" type="checkbox">
        """))
        try:
            page = context.new_page()
            page.goto("https://www.webdesk.it/Account/AccessNewLocation.aspx")
            runner = DedicatedRunner(page)
            assert webdesk_validation.perform(runner, DEDICATED)["stage"] == "code"
            result = webdesk_validation.perform(runner, DEDICATED, "submit", "test@example.test", "Ab1234")
            assert result["stage"] == "changed"
            assert page.evaluate("window.submitted || false") is False
            assert not page.locator("#MainContent_chkAccess").is_checked()
        finally:
            browser.close()
