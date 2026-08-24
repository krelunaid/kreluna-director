import json

from app.models import Device
from app.services.agents import _needs_update, compose_agent_rows
from app.services.registry import allowed_capabilities, score_agent


def a_device(role: str, declared: list[str]) -> Device:
    return Device(
        id="d1",
        tenant_id="t1",
        agent_id=role,
        hostname="MacBook-di-prova.local",
        display_name=role.upper(),
        public_key="k",
        fingerprint="f",
        capabilities=json.dumps(declared),
        platform="macos",
        status="active",
        presence="online",
        busy=False,
        killed=False,
        paused=False,
        recent_errors=0,
    )


def test_the_studio_policy_decides_the_jobs_not_the_pc():
    """Un Agent vecchio dichiara i lavori di un'altra versione: si ignora."""

    old = a_device("pc-visure", ["notepad_write", "email_draft", "payment_prepare"])
    assert "visure_prepare" in allowed_capabilities(old)
    assert "portal_open" in allowed_capabilities(old)
    assert score_agent(old, "visure_prepare") > 0
    assert score_agent(old, "payment_prepare") == -10_000, "il ruolo non prevede pagamenti"


def test_an_unknown_role_still_uses_what_it_declares():
    custom = a_device("pc-di-prova", ["notepad_write"])
    assert allowed_capabilities(custom) == ["notepad_write"]
    assert score_agent(custom, "notepad_write") > 0
    assert score_agent(custom, "visure_prepare") == -10_000


def test_the_refusal_is_explained_in_italian():
    from app.routers.agent_io import _readable_error

    old = a_device("pc-visure", ["notepad_write"])
    message = _readable_error("CAPABILITY_NOT_ALLOWED", old)
    assert "Agent vecchio" in message
    assert "PC-VISURE" in message

    current = a_device("pc-visure", ["visure_prepare", "document_check", "portal_open"])
    wrong_pc = _readable_error("CAPABILITY_NOT_ALLOWED", current)
    assert "non è il PC che fa questo lavoro" in wrong_pc

    assert _readable_error("PORTALE_SCONOSCIUTO:x", current) == "PORTALE_SCONOSCIUTO:x"
    assert _readable_error(None, current)


def test_an_old_agent_is_flagged_and_a_current_one_is_not():
    old = a_device("pc-visure", ["notepad_write", "email_draft"])
    current = a_device("pc-visure", ["visure_prepare", "document_check", "portal_open"])
    assert _needs_update(old) is True
    assert _needs_update(current) is False
    rows = compose_agent_rows([old], [])
    assert rows[0]["needs_update"] is True
    assert rows[0]["agent_id"] == "pc-visure"
