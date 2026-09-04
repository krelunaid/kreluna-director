import pytest
from agent.capabilities.portal import _webdesk_mail_validation
from agent.tools import mac_browser, webdesk_validation


def test_guard_is_specific_and_does_not_trust_device():
    script = webdesk_validation.script("Safari", "submit", "test@example.test", "123456")
    assert "/Account/AccessNewLocation.aspx" in script
    assert "location.origin" in script
    assert "MainContent_CodSicurezza" in script
    assert "MainContent_ChangePasswordPushButton" in script
    assert "recipient!==" in script
    assert "MainContent_chkAccess" not in script  # No automatic trusted-device checkbox.
    assert "count of tabs of candidateWindow" in script


def test_browser_errors_never_expose_code():
    class BadRunner:
        def osascript(self, script): raise mac_browser.MacControlError(script)
    assert webdesk_validation.perform(BadRunner(), "Safari", "submit", "test@example.test", "123456") == {"stage": "unknown"}


def test_validated_page_continues_without_requesting_another_code(monkeypatch):
    actions = []
    def perform(*args):
        actions.append(args[2])
        return {"acted": True}
    monkeypatch.setattr(webdesk_validation, "perform", perform)
    _webdesk_mail_validation(None, "Safari", {"stage": "validated"}, "", "", "", None, lambda _: None, lambda: None)
    assert actions == ["continue"]
    script = webdesk_validation.script("Safari", "continue")
    assert "MainContent_VaiWebdesLink" in script
    assert "correttament[ae]" in script  # The live site spells it 'correttamenta'.


@pytest.mark.parametrize("stage", ["code", "unknown", "other"])
def test_already_requested_or_unknown_challenge_not_reused(stage):
    with pytest.raises(RuntimeError):
        _webdesk_mail_validation(None, "Safari", {"stage": stage}, "", "", "", None, lambda _: None, lambda: None)


def test_code_flow_rechecks_page_and_confirms_navigation(monkeypatch):
    calls = []
    class Response:
        is_success = True
        def __init__(self, body): self.body = body
        def json(self): return self.body
    def post(url, **kwargs):
        calls.append(url)
        return Response({"challenge_id": "one"} if url.endswith("start") else {"pending": False, "code": "123456"})
    monkeypatch.setattr("agent.capabilities.portal.httpx.post", post)
    states = iter([{"acted": True}, {"stage": "code", "recipient": "test@example.test"}, {"acted": True}, {"stage": "other"}])
    monkeypatch.setattr(webdesk_validation, "perform", lambda *args: next(states))
    _webdesk_mail_validation(None, "Safari", {"stage": "request", "recipient": "test@example.test"},
        "https://director.example.test", "device", "task", lambda path, payload: payload, lambda _: None, lambda: None)
    assert len(calls) == 2


@pytest.mark.parametrize("changed_recipient", [False, True])
def test_safari_transient_page_and_late_email(monkeypatch, changed_recipient):
    actions, polls = [], []
    class Response:
        is_success = True
        def __init__(self, data): self.data = data
        def json(self): return self.data
    def post(url, **kwargs):
        if url.endswith("start"):
            return Response({"challenge_id": "test"})
        polls.append(1)
        return Response({"pending": True} if len(polls) < 20 else {"code": "123456"})
    reads = 0
    def perform(run, browser, action="inspect", *args):
        nonlocal reads
        actions.append(action)
        if action != "inspect": return {"acted": True}
        reads += 1
        if reads <= 2: return {"stage": "unknown"}
        if "submit" in actions: return {"stage": "validated"}
        return {"stage": "code", "recipient": "other@example.test" if changed_recipient else "test@example.test"}
    monkeypatch.setattr("agent.capabilities.portal.httpx.post", post)
    monkeypatch.setattr(webdesk_validation, "perform", perform)
    def run():
        _webdesk_mail_validation(None, "Safari", {"stage": "request", "recipient": "test@example.test"},
            "https://director.example.test", "d", "t", lambda p, b: b, lambda _: None, lambda: None)
    if changed_recipient:
        with pytest.raises(RuntimeError, match="destinatario"): run()
        assert not polls and "submit" not in actions
    else:
        run()
        assert len(polls) == 20
        assert actions.count("request") == actions.count("submit") == actions.count("continue") == 1
