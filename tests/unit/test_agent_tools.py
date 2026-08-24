from agent.capabilities.documents import check
from agent.capabilities.notepad import write_notepad
from agent.tools.gestionale import fill_invoice_on_pc, show_invoice_on_this_mac
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


def test_invoice_gestionale_types_client_and_shows_mouse():
    shots = fill_invoice_on_pc(
        client_name="Andrea Gadducci",
        description="Manodopera",
        net_eur=37500,
    )
    assert len(shots) >= 3
    last = shots[-1]
    assert last["sha256"] == sha256_hex(last["png"])
    assert last["png"].startswith(b"\x89PNG")
    assert last["metadata"]["mouse"] is True
    assert last["metadata"]["program"] == "gestionale-fatture-demo"


def test_live_mac_window_skipped_on_linux():
    assert show_invoice_on_this_mac(client_name="Andrea Gadducci", description="Manodopera", net_eur=37500) is False
