#!/usr/bin/env python3
"""Download relocatable CPython and vendor wheels for Mac/Windows installers."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

RELEASE = "20260325"
PY_VER = "3.12.13"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}"

PLATFORMS = {
    "macos-arm64": {
        "archive": f"cpython-{PY_VER}+{RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz",
        # Never include universal2: macOS treats those wheels as Intel and shows
        # "App basate su Intel non più supportate" on Apple Silicon.
        "pip_platforms": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64"],
        "extra": [],
    },
    "macos-x64": {
        "archive": f"cpython-{PY_VER}+{RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz",
        "pip_platforms": ["macosx_11_0_x86_64", "macosx_10_13_x86_64", "macosx_10_9_x86_64"],
        "extra": [],
    },
    "windows-x64": {
        "archive": f"cpython-{PY_VER}+{RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "pip_platforms": ["win_amd64"],
        "extra": ["pywinauto>=0.6.8", "colorama>=0.4.6"],
    },
}

COMMON_PKGS = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "httptools>=0.6.0",
    "watchfiles>=1.0.0",
    "sqlalchemy>=2.0.36",
    "aiosqlite>=0.20.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "pyyaml>=6.0.2",
    "httpx>=0.28.0",
    "cryptography>=44.0.0",
    "pillow>=11.0.0",
    "websockets>=14.0",
    "python-multipart>=0.0.18",
]


def cache_dir(root: Path) -> Path:
    path = root / ".cache" / "python-standalone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_archive(root: Path, filename: str) -> Path:
    dest = cache_dir(root) / filename
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    url = f"{BASE}/{filename}"
    print(f"Scarico {filename}…")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    return dest


def extract_python(archive: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    nested = dest / "python"
    if nested.is_dir() and not (dest / "bin").exists() and not (dest / "python.exe").exists():
        for child in nested.iterdir():
            shutil.move(str(child), dest / child.name)
        nested.rmdir()
    return dest


def site_packages(python_home: Path) -> Path:
    win = python_home / "Lib" / "site-packages"
    if win.parent.is_dir() or (python_home / "python.exe").exists():
        win.mkdir(parents=True, exist_ok=True)
        return win
    unix = python_home / "lib" / "python3.12" / "site-packages"
    unix.mkdir(parents=True, exist_ok=True)
    return unix


def assert_no_intel_artifacts(python_home: Path, key: str) -> None:
    """Fail the Mac arm64 bundle if any Intel/universal2 slice leaked in."""
    if key != "macos-arm64":
        return
    offenders: list[str] = []
    for path in python_home.rglob("*"):
        name = path.name.lower()
        if any(marker in name for marker in ("x86_64", "universal2")):
            offenders.append(str(path.relative_to(python_home)))
            continue
        if path.is_file() and path.name == "WHEEL":
            text = path.read_text(errors="ignore").lower()
            if "x86_64" in text or "universal2" in text:
                offenders.append(str(path.relative_to(python_home)))
    if offenders:
        preview = "\n".join(offenders[:40])
        raise SystemExit(f"Intel/universal2 nel runtime arm64:\n{preview}")


def vendor_wheels(python_home: Path, pip_platforms: list[str], extra: list[str]) -> None:
    target = site_packages(python_home)
    pkgs = COMMON_PKGS + extra
    last_error: subprocess.CalledProcessError | None = None
    for pip_platform in pip_platforms:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-compile",
            "--disable-pip-version-check",
            "--python-version",
            "312",
            "--platform",
            pip_platform,
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--only-binary",
            ":all:",
            "--target",
            str(target),
            *pkgs,
        ]
        print("Installo dipendenze per", pip_platform)
        try:
            subprocess.check_call(cmd)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error


def bundle(root: Path, key: str, dest: Path) -> Path:
    spec = PLATFORMS[key]
    archive = fetch_archive(root, spec["archive"])
    extract_python(archive, dest)
    vendor_wheels(dest, spec["pip_platforms"], spec["extra"])
    assert_no_intel_artifacts(dest, key)
    marker = dest / "KRELUNA_RUNTIME.txt"
    marker.write_text(f"{key}\n{spec['archive']}\nsha256={sha256(archive)}\n")
    return dest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=sorted(PLATFORMS))
    parser.add_argument("dest")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    bundle(Path(args.root), args.platform, Path(args.dest))
    print("Runtime pronto:", args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
