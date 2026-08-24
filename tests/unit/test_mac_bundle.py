from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_thin_fat_macho_keeps_only_arm64(tmp_path):
    module = _load_bundle_module()
    cpu_x64 = 0x01000007
    cpu_arm = 0x0100000C
    x64_payload = b"INTEL-SLICE!!!!"
    arm_payload = b"ARM64-SLICE!!!!"
    offset_x64 = 64
    offset_arm = 96
    header = struct.pack(">II", 0xCAFEBABE, 2)
    header += struct.pack(">iiIII", cpu_x64, 0, offset_x64, len(x64_payload), 0)
    header += struct.pack(">iiIII", cpu_arm, 0, offset_arm, len(arm_payload), 0)
    blob = header.ljust(offset_x64, b"\x00") + x64_payload
    blob = blob.ljust(offset_arm, b"\x00") + arm_payload
    path = tmp_path / "fat.so"
    path.write_bytes(blob)
    assert module.thin_fat_macho_to_arm64(path) is True
    assert path.read_bytes() == arm_payload


def test_macos_site_packages_uses_python_version_directory(tmp_path):
    module = _load_bundle_module()
    (tmp_path / "lib").mkdir()

    target = module.site_packages(tmp_path)

    assert target == tmp_path / "lib" / "python3.12" / "site-packages"


def _load_bundle_module():
    import importlib.util

    path = ROOT / "scripts" / "lib" / "bundle_python.py"
    spec = importlib.util.spec_from_file_location("kreluna_bundle_python", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_macos_arm64_director_bundle_has_server_runtime_and_no_intel():
    module = _load_bundle_module()
    spec = module.PLATFORMS["macos-arm64"]
    joined = " ".join(spec["pip_platforms"])
    assert "universal2" not in joined
    assert "x86_64" not in joined
    assert all("arm64" in tag for tag in spec["pip_platforms"])
    extra = " ".join(spec["extra"]).lower()
    assert "uvloop" not in extra
    packages = " ".join(spec.get("packages") or module.COMMON_PKGS).lower()
    assert "sqlalchemy" in packages
    assert "greenlet" in packages
    assert "fastapi" in packages
    assert "argon2-cffi" in packages
    assert "aarch64-apple-darwin" in spec["archive"]
    assert "x86_64" not in spec["archive"]


def test_macos_arm64_agent_bundle_stays_small_and_has_no_server():
    module = _load_bundle_module()
    spec = module.PLATFORMS["macos-arm64-agent"]
    packages = " ".join(spec.get("packages") or []).lower()
    assert "sqlalchemy" not in packages
    assert "greenlet" not in packages
    assert "uvloop" not in packages
    assert "fastapi" not in packages
    assert "aarch64-apple-darwin" in spec["archive"]
    assert "x86_64" not in spec["archive"]


def test_mac_agent_build_script_skips_intel_python():
    script = (ROOT / "scripts" / "macos" / "build-mac-agent.sh").read_text()
    assert "macos-arm64-agent" in script
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
