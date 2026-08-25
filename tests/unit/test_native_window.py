from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_native_window():
    path = ROOT / "apps" / "director-desktop" / "native_window.py"
    spec = importlib.util.spec_from_file_location("kreluna_native_window", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_window_only_accepts_local_director() -> None:
    module = _load_native_window()

    assert module.validated_local_url("http://127.0.0.1:8080/").endswith(":8080/")
    with pytest.raises(ValueError, match="soltanto"):
        module.validated_local_url("https://example.com/")
    with pytest.raises(ValueError, match="soltanto"):
        module.validated_local_url("http://127.0.0.1:9000/")


def test_macos_packaged_app_runs_its_native_helper(monkeypatch, tmp_path: Path) -> None:
    module = _load_native_window()
    helper = tmp_path / "KrelunaWindow"
    helper.write_text("native")
    calls: list[list[str]] = []

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setenv("KRELUNA_NATIVE_WINDOW", str(helper))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, check: calls.append(command)
        or subprocess.CompletedProcess(command, returncode=0),
    )

    module.run_native_window("http://127.0.0.1:8080/", storage_path=tmp_path / "storage")

    assert calls == [[str(helper), "http://127.0.0.1:8080/"]]


def test_windows_packaged_app_uses_webview2_and_persistent_storage(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_native_window()
    created: list[tuple[tuple, dict]] = []
    started: list[dict] = []
    fake = SimpleNamespace(
        settings={},
        create_window=lambda *args, **kwargs: created.append((args, kwargs)),
        start=lambda **kwargs: started.append(kwargs),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)

    storage = tmp_path / "webview"
    module._run_windows_window("http://127.0.0.1:8080/", storage_path=storage)

    assert storage.is_dir()
    assert created[0][0] == ("Kreluna Director", "http://127.0.0.1:8080/")
    assert started == [
        {
            "gui": "edgechromium",
            "debug": False,
            "private_mode": False,
            "storage_path": str(storage),
        }
    ]
    assert fake.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
