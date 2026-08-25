from __future__ import annotations

import importlib.util
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
