from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from kreluna_shared.windows_update import (
    APP_DIR_NAME,
    WindowsUpdateError,
    app_version,
    parse_checksum,
    validate_app,
    validate_update_archive,
)


def fake_app(root: Path, version: str = "9.0.0") -> Path:
    app = root / APP_DIR_NAME
    required = [
        app / "runtime" / "python.exe",
        app / "apps" / "director-desktop" / "kreluna_desktop.py",
        app / "apps" / "director-web" / "dist" / "index.html",
        app / "Avvia.bat",
        app / "Avvia.vbs",
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    update = app / "packages" / "kreluna-shared" / "src" / "kreluna_shared" / "update.py"
    update.parent.mkdir(parents=True, exist_ok=True)
    update.write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
    return app


def test_parse_checksum_accepts_only_windows_asset():
    digest = "b" * 64
    assert parse_checksum(f"{digest}  Kreluna-Director-Windows.zip\n") == digest
    with pytest.raises(WindowsUpdateError):
        parse_checksum(f"{digest}  altro.zip\n")


def test_validate_windows_app_checks_required_files_and_version(tmp_path):
    app = fake_app(tmp_path)
    assert app_version(app) == "9.0.0"
    validate_app(app, "9.0.0")
    with pytest.raises(WindowsUpdateError, match="versione"):
        validate_app(app, "9.0.1")
    (app / "runtime" / "python.exe").unlink()
    with pytest.raises(WindowsUpdateError, match="incompleto"):
        validate_app(app, "9.0.0")


def test_windows_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as destination:
        destination.writestr("../outside", "no")
    with pytest.raises(WindowsUpdateError, match="percorso non sicuro"):
        validate_update_archive(archive)


def test_windows_archive_accepts_expected_layout(tmp_path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as destination:
        destination.writestr(f"{APP_DIR_NAME}/Avvia.bat", "ok")
        destination.writestr("Installa.ps1", "ok")
    validate_update_archive(archive)
