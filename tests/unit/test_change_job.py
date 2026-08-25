import os
from pathlib import Path


def test_each_job_gets_its_own_folder_even_with_a_shared_default(tmp_path, monkeypatch):
    """Il lanciatore del Mac imposta una cartella unica: il ruolo deve avere la sua."""

    from agent import mac_boot

    monkeypatch.setattr(mac_boot, "support_dir", lambda: tmp_path)
    monkeypatch.setenv("KRELUNA_AGENT_DATA_DIR", str(tmp_path / "data"))
    mac_boot.apply_config(
        {
            "role": "pc-visure",
            "display_name": "PC-VISURE",
            "director_url": "http://127.0.0.1:8080",
        }
    )
    first = Path(os.environ["KRELUNA_AGENT_DATA_DIR"])
    assert first.name == "pc-visure"

    monkeypatch.setenv("KRELUNA_AGENT_DATA_DIR", str(tmp_path / "data"))
    mac_boot.apply_config(
        {
            "role": "pc-fatture",
            "display_name": "PC-FATTURE",
            "director_url": "http://127.0.0.1:8080",
        }
    )
    second = Path(os.environ["KRELUNA_AGENT_DATA_DIR"])
    assert second.name == "pc-fatture"
    assert first != second, "due lavori non possono condividere la stessa identità"


def test_an_agent_can_forget_only_a_rejected_enrollment(tmp_path):
    from agent.identity import AgentIdentity

    identity = AgentIdentity(tmp_path, "pc-fatture", "PC-FATTURE")
    identity.save_enrollment("vecchio-device", "vecchio-studio")
    key_before = identity.key_path.read_bytes()

    identity.clear_enrollment()

    assert identity.device_id is None
    assert identity.tenant_id is None
    assert not identity.state_path.exists()
    assert identity.key_path.read_bytes() == key_before


def test_mac_enrollment_code_is_a_one_time_file_not_saved_in_config(tmp_path, monkeypatch):
    from agent import mac_boot

    monkeypatch.setattr(mac_boot, "support_dir", lambda: tmp_path)
    code = "KRELUNA-ENROLL-" + "b" * 43
    data = {
        "role": "pc-fatture",
        "display_name": "PC-FATTURE",
        "director_url": "http://127.0.0.1:8080",
        "enrollment_code": code,
    }

    mac_boot.save_config(data)

    assert "enrollment_code" not in mac_boot.load_config()
    assert mac_boot.enrollment_path().read_text(encoding="utf-8").strip() == code
    assert mac_boot.enrollment_path().stat().st_mode & 0o777 == 0o600
