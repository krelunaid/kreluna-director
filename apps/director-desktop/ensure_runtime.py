#!/usr/bin/env python3
"""Crea o aggiorna l'ambiente Python locale quando cambia la versione dell'app."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def ensure(root: Path, support: Path, venv: Path, creator: str | None = None) -> Path:
    sys.path.insert(0, str(root / "packages" / "kreluna-shared" / "src"))
    from kreluna_shared.update import APP_VERSION, runtime_needs_refresh, write_installed_version

    support.mkdir(parents=True, exist_ok=True)
    py = venv_python(venv)
    need_venv = not py.exists()
    need_pip = need_venv or runtime_needs_refresh(support, APP_VERSION)
    python = creator or sys.executable
    if need_venv:
        subprocess.check_call([python, "-m", "venv", str(venv)])
        py = venv_python(venv)
        subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    if need_pip:
        subprocess.check_call([str(py), "-m", "pip", "install", "-e", str(root)])
        write_installed_version(support, APP_VERSION)
    print(str(py))
    return py


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("support")
    parser.add_argument("venv")
    args = parser.parse_args()
    ensure(Path(args.root), Path(args.support), Path(args.venv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
