import pytest
from agent.tools import mac_browser
from agent.tools.browser_command import DEDICATED, BrowserCommand
from agent.tools.dedicated_browser import BrowserService, DedicatedRunner, allowed_url


@pytest.mark.parametrize("url", [
    "http://app.webdesk.it/", "https://app.webdesk.it.evil.test/",
    "https://app.webdesk.it:444/", "https://user@app.webdesk.it/",
    "file:///tmp/test", "https://127.0.0.1/", "https://app.webdesk.it:bad/",
])
def test_rejects_other_origins(url):
    assert not allowed_url(url)


def test_official_origins():
    assert allowed_url("https://app.webdesk.it/Apps/Login/View")
    assert allowed_url("https://sme.genya.it/Elements/Factory/Screens/MainSmartInvoice/MainSmartInvoice.html")


class Page:
    url = "https://app.webdesk.it/Apps/Login/View"
    closed = False
    scripts = None

    def is_closed(self):
        return self.closed

    def evaluate(self, script):
        self.scripts = script
        return "CLICCATO SCRITTO"


def test_typed_only_and_redacted_errors():
    page = Page()
    runner = DedicatedRunner(page)
    with pytest.raises(mac_browser.MacControlError):
        runner.osascript('tell application "Safari" to activate')
    secret = "private-test-placeholder"
    assert secret not in repr(BrowserCommand("evaluate", secret))
    def fail(_):
        raise RuntimeError(secret)
    page.evaluate = fail
    with pytest.raises(mac_browser.MacControlError) as caught:
        runner.osascript(BrowserCommand("evaluate", secret))
    assert secret not in str(caught.value)


@pytest.mark.parametrize("read_only,expected", [(True, 2), (False, 1)])
def test_navigation_retry_is_read_only(read_only, expected):
    page = Page()
    calls = []
    def evaluate(script):
        calls.append(script)
        if len(calls) == 1:
            raise RuntimeError("Execution context was destroyed")
        return "TROVATO"
    page.evaluate = evaluate
    page.wait_for_load_state = lambda *args, **kwargs: None
    command = BrowserCommand("evaluate", "document.title", read_only=read_only)
    if read_only:
        assert DedicatedRunner(page).osascript(command) == "TROVATO"
    else:
        with pytest.raises(mac_browser.MacControlError):
            DedicatedRunner(page).osascript(command)
    assert len(calls) == expected


def test_closed_or_replaced_page_fails():
    page = Page()
    runner = DedicatedRunner(page)
    page.url = "https://example.com/"
    with pytest.raises(mac_browser.MacControlError):
        runner.osascript(BrowserCommand("evaluate", "document.title"))
    page.url = Page.url
    page.closed = True
    with pytest.raises(mac_browser.MacControlError):
        runner.osascript(BrowserCommand("url"))


def test_no_pointer_or_applescript_for_dedicated_controls():
    page = Page()
    runner = DedicatedRunner(page)
    def forbidden(*args, **kwargs):
        pytest.fail("Desktop pointer used")
    assert mac_browser.pick_browser(runner, "Safari") == DEDICATED
    assert mac_browser.fill_field_visible(runner, DEDICATED, "#password", "test", mover=forbidden) == (True, False)
    assert mac_browser.click_selector_visible(runner, DEDICATED, "#submitButton", mover=forbidden)
    assert mac_browser.click_text_in_section(runner, DEDICATED, "Fatture", "Nuova", mover=forbidden)
    mac_browser.click_invoice_line_vat(runner, DEDICATED, 0, "22%", mover=forbidden)
    assert "location.protocol" in page.scripts
    with pytest.raises(mac_browser.MacControlError):
        runner.screencapture(None)


@pytest.mark.parametrize("action", ["Salva", "Emetti", "Invia", "Trasmetti", "Paga"])
def test_invoice_final_actions_still_blocked(action):
    with pytest.raises(RuntimeError, match="VIETATA"):
        mac_browser.click_text_in_section(DedicatedRunner(Page()), DEDICATED, "Fatture", action)


def test_concurrent_request_rejected_without_queueing():
    service = BrowserService()
    service.lock.acquire()
    try:
        with pytest.raises(mac_browser.MacControlError, match="occupato"):
            service.run(lambda: pytest.fail("must not run"), {})
    finally:
        service.lock.release()
        service.close()


def test_portal_opt_in_dispatches_without_legacy_runner(monkeypatch):
    from agent.capabilities.portal import open_portal
    from agent.tools import dedicated_browser
    calls = []
    monkeypatch.setenv("KRELUNA_WEBDESK_BROWSER", "dedicated")
    monkeypatch.setattr(dedicated_browser, "run_webdesk", lambda fn, kw: calls.append(kw) or {"test": True})
    assert open_portal("fatture-webdesk", director_url="local", device_id="device") == {"test": True}
    assert calls[0]["portal"] == "fatture-webdesk"
