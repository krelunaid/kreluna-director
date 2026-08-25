from __future__ import annotations

import importlib.util
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _desktop_module():
    path = ROOT / "apps" / "director-desktop" / "kreluna_desktop.py"
    spec = importlib.util.spec_from_file_location("kreluna_managed_ai_desktop", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desktop_loads_only_a_valid_revocable_license_file(tmp_path, monkeypatch):
    desktop = _desktop_module()
    monkeypatch.setattr(desktop, "SUPPORT", tmp_path)
    path = tmp_path / "managed_ai.token"
    token = "kreluna_live_" + "A" * 43
    path.write_text(token + "\n", encoding="utf-8")

    assert desktop._managed_ai_token() == token
    assert path.stat().st_mode & 0o777 == 0o600

    path.write_text("xai-secret-must-never-be-loaded-here\n", encoding="utf-8")
    assert desktop._managed_ai_token() == ""


def test_desktop_creates_stable_distinct_installation_secrets_and_owner(tmp_path, monkeypatch):
    desktop = _desktop_module()
    monkeypatch.setattr(desktop, "SUPPORT", tmp_path)
    names = (
        "DIRECTOR_SIGNING_SEED",
        "DIRECTOR_SESSION_SECRET",
        "DIRECTOR_EVIDENCE_KEY",
        "DIRECTOR_CREDENTIAL_KEY",
        "DIRECTOR_BOOTSTRAP_EMAIL",
        "DIRECTOR_BOOTSTRAP_PASSWORD",
        "DIRECTOR_ENV",
    )
    monkeypatch.setattr(desktop.os, "environ", {})

    desktop.prepare_env()
    first = {name: desktop.os.environ[name] for name in names}
    desktop.prepare_env()
    second = {name: desktop.os.environ[name] for name in names}

    secrets = [first[name] for name in names[:4]]
    assert len(set(secrets)) == 4
    assert all(len(value) >= 32 for value in secrets)
    assert first == second
    assert first["DIRECTOR_ENV"] == "desktop"
    assert first["DIRECTOR_BOOTSTRAP_EMAIL"] != "andrea@studio.demo"
    assert len(first["DIRECTOR_BOOTSTRAP_PASSWORD"]) >= 20
    for filename in ("signing.seed", "session.key", "evidence.key", "credential.key", "owner-access.json"):
        assert (tmp_path / filename).stat().st_mode & 0o777 == 0o600


def test_packaged_director_starts_only_a_verified_configured_local_agent(tmp_path, monkeypatch):
    desktop = _desktop_module()
    app = tmp_path / "Kreluna Agent.app"
    executable = app / "Contents" / "MacOS" / "Kreluna"
    executable.parent.mkdir(parents=True)
    executable.write_text("agent", encoding="utf-8")
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(
            {
                "CFBundleIdentifier": "studio.kreluna.agent",
                "CFBundleExecutable": "Kreluna",
            },
            fh,
        )
    support = tmp_path / "support"
    support.mkdir()
    (support / "config.json").write_text(
        '{"role":"pc-fatture","display_name":"PC-FATTURE",'
        '"director_url":"http://127.0.0.1:8080"}',
        encoding="utf-8",
    )
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1 if command[0].endswith("pgrep") else 0)

    class FakeProcess:
        pass

    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setenv("KRELUNA_INSTALLED_AGENT_APP", str(app))
    monkeypatch.setenv("KRELUNA_AGENT_SUPPORT_DIR", str(support))
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or FakeProcess(),
    )

    process = desktop.start_installed_mac_agent()

    assert isinstance(process, FakeProcess)
    assert calls[0][0] == [str(executable)]
    assert calls[0][1]["env"]["KRELUNA_AGENT_ID"] == "pc-fatture"
    assert calls[0][1]["env"]["KRELUNA_SKIP_SETUP"] == "1"
