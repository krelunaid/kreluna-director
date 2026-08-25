from __future__ import annotations

import os
import plistlib
import zipfile
from pathlib import Path

import pytest
from kreluna_shared.macos_update import (
    APP_BUNDLE_NAME,
    BUNDLE_ID,
    MacUpdateError,
    parse_checksum,
    validate_bundle,
    validate_update_archive,
)


def fake_bundle(root: Path, version: str = "9.0.0") -> Path:
    app = root / APP_BUNDLE_NAME
    contents = app / "Contents"
    launcher = contents / "MacOS" / "Kreluna"
    python = contents / "Resources" / "python-arm64" / "bin" / "python3.12"
    index = contents / "Resources" / "app" / "apps" / "director-web" / "dist" / "index.html"
    launcher.parent.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    python.write_bytes(b"python")
    index.write_text("<html></html>", encoding="utf-8")
    launcher.chmod(0o755)
    python.chmod(0o755)
    with (contents / "Info.plist").open("wb") as destination:
        plistlib.dump(
            {
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleShortVersionString": version,
            },
            destination,
        )
    return app


def test_parse_checksum_accepts_only_expected_asset():
    digest = "a" * 64
    assert parse_checksum(f"{digest}  Kreluna-Director-Mac.zip\n") == digest
    with pytest.raises(MacUpdateError):
        parse_checksum(f"{digest}  altro.zip\n")
    with pytest.raises(MacUpdateError):
        parse_checksum("non-una-firma")


def test_validate_bundle_checks_identity_version_and_required_files(tmp_path):
    app = fake_bundle(tmp_path)
    validate_bundle(app, "9.0.0", verify_signature=False)
    with pytest.raises(MacUpdateError, match="versione"):
        validate_bundle(app, "9.0.1", verify_signature=False)

    info_path = app / "Contents" / "Info.plist"
    with info_path.open("rb") as source:
        info = plistlib.load(source)
    info["CFBundleIdentifier"] = "example.invalid"
    with info_path.open("wb") as destination:
        plistlib.dump(info, destination)
    with pytest.raises(MacUpdateError, match="non è Kreluna"):
        validate_bundle(app, "9.0.0", verify_signature=False)


def test_validate_bundle_rejects_symlink_outside_app(tmp_path):
    app = fake_bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("segreto", encoding="utf-8")
    os.symlink("../../../../../../outside", app / "Contents" / "Resources" / "unsafe")
    with pytest.raises(MacUpdateError, match="collegamento non sicuro"):
        validate_bundle(app, "9.0.0", verify_signature=False)


def test_update_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as destination:
        destination.writestr("../outside", "no")
    with pytest.raises(MacUpdateError, match="percorso non sicuro"):
        validate_update_archive(archive)
