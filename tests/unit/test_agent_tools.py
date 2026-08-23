from agent.capabilities.notepad import write_notepad
from agent.capabilities.documents import check
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
