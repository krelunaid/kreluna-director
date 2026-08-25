from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_director_package_does_not_require_or_copy_agent() -> None:
    copy_script = (ROOT / "scripts" / "lib" / "copy-app-tree.sh").read_text()
    mac_launcher = (ROOT / "packaging" / "macos" / "Kreluna").read_text()
    windows_launcher = (ROOT / "packaging" / "windows" / "Avvia.bat").read_text()

    assert "--exclude 'apps/kreluna-agent'" in copy_script
    assert "apps/kreluna-agent" not in mac_launcher
    assert "apps\\kreluna-agent" not in windows_launcher
    assert "KRELUNA_AGENT_ID" not in mac_launcher
    assert "KRELUNA_AGENT_ID" not in windows_launcher


def test_local_agent_is_explicit_opt_in_in_desktop_launcher() -> None:
    source = (ROOT / "apps" / "director-desktop" / "kreluna_desktop.py").read_text()

    assert 'os.environ.get("KRELUNA_START_LOCAL_AGENT", "")' in source
    assert "if start_local_agent" in source
    assert 'health.get("service") != "director-api"' in source


def test_mac_launcher_exposes_the_whole_app_bundle_to_updater() -> None:
    launcher = (ROOT / "packaging" / "macos" / "Kreluna").read_text()

    assert 'APP_BUNDLE="$(cd "$APP_DIR/.." && pwd)"' in launcher
    assert 'export KRELUNA_APP_BUNDLE="$APP_BUNDLE"' in launcher
    assert 'export PYTHONDONTWRITEBYTECODE="1"' in launcher
    api_main = (ROOT / "apps" / "director-api" / "app" / "main.py").read_text()
    assert 'Path(ROOT / "data").mkdir' not in api_main


def test_embedded_director_runtimes_include_password_hasher() -> None:
    import importlib.util

    path = ROOT / "scripts" / "lib" / "bundle_python.py"
    spec = importlib.util.spec_from_file_location("kreluna_bundle_desktop", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    packages = " ".join(module.COMMON_PKGS).lower()
    assert "argon2-cffi" in packages
    assert "fastapi" in packages
    assert "sqlalchemy" in packages
    assert "greenlet" in packages


def test_release_publishes_director_and_agents_for_mac_and_windows() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    for asset in (
        "Kreluna-Director-Mac.zip",
        "Kreluna-Director-Windows.zip",
        "Kreluna-Agent-Mac.zip",
        "Kreluna-Agenti-Windows.zip",
    ):
        assert asset in workflow
