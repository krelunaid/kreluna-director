from __future__ import annotations

import subprocess

from agent import browser_setup


class FakeRun:
    def __init__(self, *, installed: tuple[str, ...] = ("Safari",), ready: bool = False):
        self.installed = installed
        self.ready = ready
        self.commands: list[list[str]] = []
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.dialog_answers = ["Ho attivato: controlla"]

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.calls.append((command, kwargs))
        joined = " ".join(command)
        if command[:2] == ["/usr/bin/open", "-a"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if "id of application" in joined:
            browser = joined.split('"')[1]
            return subprocess.CompletedProcess(command, 0 if browser in self.installed else 1, "id\n", "")
        if "do JavaScript" in joined or "execute javascript" in joined:
            return subprocess.CompletedProcess(command, 0 if self.ready else 1, "READY\n" if self.ready else "", "bloccato")
        if "display dialog" in joined:
            answer = self.dialog_answers.pop(0) if self.dialog_answers else "Continua"
            if answer == "Ho attivato: controlla":
                self.ready = True
            return subprocess.CompletedProcess(command, 0, f"button returned:{answer}\n", "")
        return subprocess.CompletedProcess(command, 1, "", "")


def test_it_detects_the_installed_browser_in_supported_order():
    fake = FakeRun(installed=("Google Chrome", "Microsoft Edge"))

    assert browser_setup.installed_browser(fake) == "Google Chrome"


def test_safari_instructions_include_both_one_time_switches():
    text = browser_setup.permission_instructions("Safari")

    assert "Avanzate" in text
    assert "sviluppatori" in text
    assert "Apple Event" in text


def test_chrome_family_gets_its_own_short_instructions():
    text = browser_setup.permission_instructions("Microsoft Edge")

    assert "Microsoft Edge" in text
    assert "Visualizza" in text
    assert "Apple Event" in text


def test_guide_opens_webdesk_and_verifies_permission(monkeypatch):
    monkeypatch.setattr(browser_setup.sys, "platform", "darwin")
    fake = FakeRun(installed=("Safari",), ready=False)

    assert browser_setup.guide_browser_permissions(fake) is True
    assert any(command[:4] == ["/usr/bin/open", "-a", "Safari", browser_setup.WEBDESK_LOGIN] for command in fake.commands)
    assert sum("do JavaScript" in " ".join(command) for command in fake.commands) >= 2
    dialog_calls = [
        kwargs
        for command, kwargs in fake.calls
        if "display dialog" in " ".join(command)
    ]
    assert dialog_calls and dialog_calls[0]["timeout"] is None


def test_ready_browser_does_not_show_the_permission_dialog(monkeypatch):
    monkeypatch.setattr(browser_setup.sys, "platform", "darwin")
    fake = FakeRun(installed=("Safari",), ready=True)

    assert browser_setup.guide_browser_permissions(fake) is True
    assert not any("display dialog" in " ".join(command) for command in fake.commands)


def test_guide_can_be_reopened_even_when_browser_is_ready(monkeypatch):
    monkeypatch.setattr(browser_setup.sys, "platform", "darwin")
    fake = FakeRun(installed=("Safari",), ready=True)

    assert browser_setup.guide_browser_permissions(fake, always_show=True) is True
    assert any("display dialog" in " ".join(command) for command in fake.commands)
