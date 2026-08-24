#!/usr/bin/env python3
"""Download relocatable CPython and vendor wheels for Mac/Windows installers."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

RELEASE = "20260325"
PY_VER = "3.12.13"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}"

# Agent Mac must not pull sqlalchemy: greenlet only ships universal2 wheels,
# which trigger "App basate su Intel non più supportate" on Apple Silicon.
AGENT_PKGS = [
    "httpx==0.28.1",
    "pydantic==2.13.4",
    "pyyaml==6.0.3",
    "pillow==11.3.0",
    "websockets==15.0.1",
    "cryptography==50.0.0",
]

COMMON_PKGS = [
    # Un installer deve essere riproducibile: i range aperti causavano ore di
    # backtracking e potevano produrre due zip diversi per la stessa release.
    "fastapi==0.128.8",
    "uvicorn==0.39.0",
    "httptools==0.8.0",
    "watchfiles==1.1.1",
    "sqlalchemy==2.0.52",
    "greenlet==3.2.4",
    "aiosqlite==0.22.1",
    "pydantic==2.13.4",
    "pydantic-settings==2.11.0",
    "pyyaml==6.0.3",
    "httpx==0.28.1",
    "cryptography==50.0.0",
    "pillow==11.3.0",
    "websockets==15.0.1",
    "python-multipart==0.0.20",
    "argon2-cffi==25.1.0",
]

PLATFORMS = {
    "macos-arm64": {
        "archive": f"cpython-{PY_VER}+{RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz",
        "pip_platforms": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64"],
        "extra": [],
    },
    "macos-arm64-agent": {
        "archive": f"cpython-{PY_VER}+{RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz",
        # Never include universal2: macOS treats those wheels as Intel.
        "pip_platforms": ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_13_0_arm64", "macosx_14_0_arm64"],
        "packages": AGENT_PKGS,
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
        "extra": ["pywinauto==0.6.9", "colorama==0.4.6"],
    },
}


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
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            # Python < 3.12 non espone ancora filter=. Prima di estrarre,
            # rifiuta comunque path traversal e link che uscirebbero da dest.
            root = dest.resolve()
            for member in tar.getmembers():
                target = (dest / member.name).resolve()
                if target != root and root not in target.parents:
                    raise ValueError(f"Percorso non sicuro nell'archivio: {member.name}")
                if member.issym() or member.islnk():
                    link_target = (target.parent / member.linkname).resolve()
                    if link_target != root and root not in link_target.parents:
                        raise ValueError(f"Link non sicuro nell'archivio: {member.name}")
            tar.extractall(dest)
    nested = dest / "python"
    if nested.is_dir() and not (dest / "bin").exists() and not (dest / "python.exe").exists():
        for child in nested.iterdir():
            shutil.move(str(child), dest / child.name)
        nested.rmdir()
    return dest


def site_packages(python_home: Path) -> Path:
    win = python_home / "Lib" / "site-packages"
    # Su macOS il filesystem predefinito è case-insensitive: verificare
    # win.parent confonderebbe Lib con lib e installerebbe nel posto sbagliato.
    if (python_home / "python.exe").exists():
        win.mkdir(parents=True, exist_ok=True)
        return win
    unix = python_home / "lib" / "python3.12" / "site-packages"
    unix.mkdir(parents=True, exist_ok=True)
    return unix


def thin_fat_macho_to_arm64(path: Path) -> bool:
    """Rewrite a universal2 Mach-O file to the arm64 slice only. Linux-safe."""

    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 8:
        return False
    magic = int.from_bytes(data[:4], "big")
    fat_be = 0xCAFEBABE
    fat_le = 0xBEBAFECA
    fat64_be = 0xCAFEBABF
    fat64_le = 0xBFBAFECA
    cpu_arm64 = 0x0100000C
    if magic not in (fat_be, fat_le, fat64_be, fat64_le):
        return False
    endian = "<" if magic in (fat_le, fat64_le) else ">"
    is64 = magic in (fat64_be, fat64_le)
    nfat = struct.unpack_from(endian + "I", data, 4)[0]
    if nfat < 1 or nfat > 8:
        return False
    cursor = 8
    entry = 32 if is64 else 20
    arm_slice: bytes | None = None
    for _ in range(nfat):
        if cursor + entry > len(data):
            return False
        if is64:
            cputype, _subtype, offset, size, _align, _reserved = struct.unpack_from(
                endian + "iiQQIi", data, cursor
            )
        else:
            cputype, _subtype, offset, size, _align = struct.unpack_from(
                endian + "iiIII", data, cursor
            )
        cursor += entry
        if (cputype & 0xFFFFFFFF) != cpu_arm64:
            continue
        if offset < 0 or size < 1 or offset + size > len(data):
            return False
        arm_slice = data[offset : offset + size]
        break
    if not arm_slice:
        return False
    path.write_bytes(arm_slice)
    return True


def strip_universal2(python_home: Path) -> None:
    """Riduce eventuali wheel universal2 alla sola slice Apple Silicon."""
    for path in python_home.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if 16 <= size <= 80_000_000:
            thin_fat_macho_to_arm64(path)
        if path.name != "WHEEL":
            continue
        text = path.read_text(errors="ignore")
        if "universal2" not in text.lower() and "x86_64" not in text.lower():
            continue
        rewritten = []
        for line in text.splitlines(keepends=True):
            lower = line.lower()
            if lower.startswith("tag:") and ("universal2" in lower or "x86_64" in lower):
                rewritten.append("Tag: cp312-cp312-macosx_11_0_arm64\n")
            else:
                rewritten.append(line)
        path.write_text("".join(rewritten))


def assert_no_intel_artifacts(python_home: Path, key: str) -> None:
    """Fail the Mac arm64 bundle if any Intel/universal2 slice leaked in."""
    if not key.startswith("macos-arm64"):
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


def vendor_wheels(
    python_home: Path,
    pip_platforms: list[str],
    extra: list[str],
    packages: list[str] | None = None,
) -> None:
    target = site_packages(python_home)
    pkgs = list(packages if packages is not None else COMMON_PKGS) + extra
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
    vendor_wheels(dest, spec["pip_platforms"], spec["extra"], spec.get("packages"))
    strip_universal2(dest)
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
