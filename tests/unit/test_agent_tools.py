import pytest
from agent.capabilities.documents import check
from agent.capabilities.notepad import write_notepad
from agent.capabilities.studio import durc, visure
from agent.tools.gestionale import fill_invoice_on_pc, show_invoice_on_this_mac
from agent.tools.screen_pointer import move_and_click
from kreluna_shared.crypto import sha256_hex


def test_virtual_notepad_writes_text_and_hash():
    result = write_notepad("Kreluna Agent operativo")
    assert result["ok"] is True
    assert result["text"] == "Kreluna Agent operativo"
    shot = result["evidence"][0]
    assert shot["sha256"] == sha256_hex(shot["png"])
    assert shot["png"].startswith(b"\x89PNG")


def test_document_check_is_readonly():
    result = check()
    assert result["ok"] is True
    assert len(result["missing"]) >= 1


def test_invoice_simulator_is_removed():
    with pytest.raises(RuntimeError, match="SIMULATORE_FATTURE_RIMOSSO"):
        fill_invoice_on_pc(client_name="Cliente prova", description="Test", net_eur=100)


def test_simulator_cannot_open_on_any_platform():
    with pytest.raises(RuntimeError, match="SIMULATORE_FATTURE_RIMOSSO"):
        show_invoice_on_this_mac(client_name="Cliente prova", description="Test", net_eur=100)


def test_visible_mouse_refuses_coordinates_outside_the_screen():
    assert move_and_click(-1, 10, screen_width=1920, screen_height=1080) is False
    assert move_and_click(10, 1080, screen_width=1920, screen_height=1080) is False


def test_durc_and_visure_are_demo_only():
    durc_result = durc(client_name="Andrea Gadducci")
    assert durc_result["ok"] is True
    assert durc_result["sent"] is False
    assert durc_result["spid_used"] is False
    assert "INPS" in durc_result["program"]
    shot = durc_result["evidence"][0]
    assert shot["png"].startswith(b"\x89PNG")
    visura = visure(client_name="Andrea Gadducci")
    assert visura["sent"] is False
    assert "CGN" in visura["program"]
