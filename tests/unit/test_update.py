from __future__ import annotations

from pathlib import Path

from kreluna_shared.crypto import server_public_bytes
from kreluna_shared.update import (
    APP_VERSION,
    evaluate_update,
    is_newer,
    manifest_payload,
    release_status,
    runtime_needs_refresh,
    sign_manifest,
    trusted_release_url,
    unavailable_status,
    verify_manifest,
    write_installed_version,
)

SEED = "kreluna-dev-signing-seed-change-in-production"
ROOT = Path(__file__).resolve().parents[2]


def test_is_newer():
    assert is_newer("0.4.1", "0.4.0") is True
    assert is_newer("0.4.0", "0.4.0") is False
    assert is_newer("0.3.9", "0.4.0") is False


def test_sign_and_verify_manifest():
    payload = manifest_payload()
    signature = sign_manifest(SEED, payload)
    public = server_public_bytes(SEED)
    assert verify_manifest(public, payload, signature) is True
    assert verify_manifest(SEED, payload, signature) is True
    tampered = dict(payload)
    tampered["version"] = "9.9.9"
    assert verify_manifest(public, tampered, signature) is False
    assert verify_manifest(public, payload, "AAAA") is False


def test_evaluate_update_same_version():
    assert evaluate_update({"version": APP_VERSION}) is None
    message = evaluate_update({"version": "9.0.0", "notes": "test"})
    assert message is not None
    assert "9.0.0" in message
    assert "scarica e aggiorna" in message.lower()


def test_github_release_status_selects_the_right_installer():
    release = {
        "tag_name": "v9.0.0",
        "html_url": "https://github.com/krelunaid/kreluna-director/releases/tag/v9.0.0",
        "body": "Nuova dashboard",
        "published_at": "2026-08-25T10:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "Kreluna-Director-Mac.zip",
                "browser_download_url": (
                    "https://github.com/krelunaid/kreluna-director/releases/download/"
                    "v9.0.0/Kreluna-Director-Mac.zip"
                ),
            },
            {
                "name": "Kreluna-Director-Windows.zip",
                "browser_download_url": (
                    "https://github.com/krelunaid/kreluna-director/releases/download/"
                    "v9.0.0/Kreluna-Director-Windows.zip"
                ),
            },
        ],
    }
    mac = release_status(release, local="0.5.9", platform="darwin")
    windows = release_status(release, local="0.5.9", platform="win32")
    assert mac["available"] is True
    assert mac["latest_version"] == "9.0.0"
    assert mac["download_url"].endswith("Kreluna-Director-Mac.zip")
    assert windows["download_url"].endswith("Kreluna-Director-Windows.zip")


def test_release_status_ignores_unsafe_links_and_prereleases():
    release = {
        "tag_name": "v9.0.0",
        "html_url": "javascript:alert(1)",
        "prerelease": True,
        "assets": [
            {
                "name": "Kreluna-Director-Mac.zip",
                "browser_download_url": "https://example.invalid/Kreluna-Director-Mac.zip",
            }
        ],
    }
    result = release_status(release, local="0.5.9", platform="darwin")
    assert result["available"] is False
    assert result["download_url"] == ""
    assert result["release_url"].startswith("https://github.com/")
    assert trusted_release_url("https://example.invalid/file.zip") == ""
    assert trusted_release_url("https://release-assets.githubusercontent.com/file.zip")
    assert unavailable_status("0.5.9")["state"] == "unavailable"


def test_runtime_stamp(tmp_path):
    assert runtime_needs_refresh(tmp_path) is True
    write_installed_version(tmp_path, APP_VERSION)
    assert runtime_needs_refresh(tmp_path) is False
    write_installed_version(tmp_path, "0.0.1")
    assert runtime_needs_refresh(tmp_path) is True


def test_sidebar_update_indicator_has_idle_and_available_states():
    source = (ROOT / "apps" / "director-web" / "src" / "App.tsx").read_text()
    styles = (ROOT / "apps" / "director-web" / "src" / "styles.css").read_text()

    assert '"Nessun aggiornamento disponibile"' in source
    assert '"Aggiornamento disponibile"' in source
    assert "disabled={!updateAvailable}" in source
    assert "updateAvailable ? <strong>Aggiornamento</strong> : null" in source
    assert ".sidebar-update.available > .sidebar-update-dot" in styles
    assert "background: var(--red)" in styles
    assert '"Installa ora"' in source
    assert "api.installUpdate()" in source
    assert "15 * 60 * 1000" in source
