from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_bundle_module():
    import importlib.util

    path = ROOT / "scripts" / "lib" / "bundle_python.py"
    spec = importlib.util.spec_from_file_location("kreluna_bundle_python", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_macos_arm64_bundle_has_no_intel_or_universal2():
    module = _load_bundle_module()
    spec = module.PLATFORMS["macos-arm64"]
    joined = " ".join(spec["pip_platforms"])
    assert "universal2" not in joined
    assert "x86_64" not in joined
    assert all("arm64" in tag for tag in spec["pip_platforms"])
    extra = " ".join(spec["extra"]).lower()
    assert "uvloop" not in extra
    assert "aarch64-apple-darwin" in spec["archive"]
    assert "x86_64" not in spec["archive"]


def test_mac_agent_build_script_skips_intel_python():
    script = (ROOT / "scripts" / "macos" / "build-mac-agent.sh").read_text()
    assert "macos-arm64" in script
    assert "macos-x64" not in script
    launcher = (ROOT / "packaging" / "macos-agent" / "Kreluna").read_text()
    assert "python-x64" not in launcher
    assert '!= "arm64"' in launcher
    plist = (ROOT / "packaging" / "macos-agent" / "Info.plist").read_text()
    assert "LSRequiresNativeExecution" in plist
    assert "<string>arm64</string>" in plist


def test_mac_director_build_script_skips_intel_python():
    script = (ROOT / "scripts" / "macos" / "build-mac-app.sh").read_text()
    assert "macos-x64" not in script
    launcher = (ROOT / "packaging" / "macos" / "Kreluna").read_text()
    assert "python-x64" not in launcher
