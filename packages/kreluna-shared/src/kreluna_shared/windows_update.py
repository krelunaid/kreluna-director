from __future__ import annotations

import hashlib
import hmac
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from kreluna_shared.update import is_newer, trusted_release_url

DOWNLOAD_NAME = "Kreluna-Director-Windows.zip"
APP_DIR_NAME = "Kreluna Director"
MAX_ARCHIVE_BYTES = 700 * 1024 * 1024
MAX_EXPANDED_BYTES = 1400 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MAX_ARCHIVE_ENTRIES = 25_000
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


class WindowsUpdateError(RuntimeError):
    """Errore esplicito durante un aggiornamento Windows."""


@dataclass(frozen=True)
class StagedWindowsUpdate:
    installer: Path
    app: Path
    version: str
    work_dir: Path


def _trusted_url(value: Any) -> str:
    url = trusted_release_url(value)
    if not url:
        raise WindowsUpdateError("Il collegamento dell'aggiornamento non è attendibile.")
    return url


def _download(url: str, destination: Path, *, limit: int) -> None:
    request = urllib.request.Request(
        _trusted_url(url),
        headers={"User-Agent": "Kreluna-Director-Updater/1"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except Exception as exc:
        raise WindowsUpdateError("Non riesco a scaricare l'aggiornamento.") from exc
    with response:
        _trusted_url(response.geturl())
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > limit:
            raise WindowsUpdateError("Il file di aggiornamento è troppo grande.")
        total = 0
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise WindowsUpdateError("Il file di aggiornamento è troppo grande.")
                output.write(chunk)


def parse_checksum(text: str, filename: str = DOWNLOAD_NAME) -> str:
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts or not SHA256_RE.fullmatch(parts[0]):
            continue
        if len(parts) == 1 or parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    raise WindowsUpdateError("La firma SHA-256 dell'aggiornamento non è valida.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_update_archive(archive: Path) -> None:
    allowed_roots = {
        APP_DIR_NAME,
        "Installa.bat",
        "Installa.ps1",
        "Install-KrelunaAgent.ps1",
        "LEGGIMI-WINDOWS.txt",
    }
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise WindowsUpdateError("Il pacchetto contiene troppi file.")
            expanded = 0
            seen: set[str] = set()
            for entry in entries:
                name = entry.filename.rstrip("/")
                path = PurePosixPath(name)
                if (
                    not name
                    or name in seen
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\x00" in name
                    or "\\" in name
                ):
                    raise WindowsUpdateError("Il pacchetto contiene un percorso non sicuro.")
                seen.add(name)
                if path.parts[0] not in allowed_roots:
                    raise WindowsUpdateError("Il pacchetto contiene file non previsti.")
                if path.parts[0] != APP_DIR_NAME and len(path.parts) != 1:
                    raise WindowsUpdateError("Il pacchetto contiene un percorso non sicuro.")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise WindowsUpdateError("Il pacchetto contiene un collegamento non sicuro.")
                expanded += entry.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise WindowsUpdateError("Il pacchetto estratto è troppo grande.")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise WindowsUpdateError("Il file di aggiornamento non è uno ZIP valido.") from exc


def app_version(app: Path) -> str:
    source = app / "packages" / "kreluna-shared" / "src" / "kreluna_shared" / "update.py"
    try:
        match = VERSION_RE.search(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise WindowsUpdateError("Il pacchetto Windows non contiene una versione valida.") from exc
    if not match:
        raise WindowsUpdateError("Il pacchetto Windows non contiene una versione valida.")
    return match.group(1)


def validate_app(app: Path, expected_version: str) -> None:
    required = [
        app / "runtime" / "python.exe",
        app / "apps" / "director-desktop" / "kreluna_desktop.py",
        app / "apps" / "director-web" / "dist" / "index.html",
        app / "Avvia.bat",
        app / "Avvia.vbs",
    ]
    if not app.is_dir() or app.is_symlink() or any(not item.is_file() for item in required):
        raise WindowsUpdateError("Il pacchetto Windows è incompleto.")
    if app_version(app) != expected_version:
        raise WindowsUpdateError("La versione scaricata non corrisponde all'aggiornamento.")


def stage_windows_update(
    status: dict[str, Any],
    *,
    current_app: Path,
    support_dir: Path,
) -> StagedWindowsUpdate:
    if sys.platform != "win32":
        raise WindowsUpdateError("L'installazione automatica Windows richiede Windows.")
    version = str(status.get("latest_version") or "").strip()
    if status.get("available") is not True or not version:
        raise WindowsUpdateError("Non ci sono aggiornamenti da installare.")
    expected_app = (support_dir / "app").resolve()
    if current_app.resolve() != expected_app:
        raise WindowsUpdateError("Kreluna Director non risulta installata nella cartella prevista.")
    current_version = app_version(expected_app)
    if not is_newer(version, current_version):
        raise WindowsUpdateError("Non ci sono aggiornamenti da installare.")
    if str(status.get("platform") or "") != "windows":
        raise WindowsUpdateError("Questo pacchetto non è destinato a Windows.")

    updates = support_dir / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="kreluna-update-", dir=updates))
    archive = work_dir / DOWNLOAD_NAME
    checksum_file = work_dir / f"{DOWNLOAD_NAME}.sha256"
    extracted = work_dir / "estratto"
    extracted.mkdir()
    try:
        _download(_trusted_url(status.get("checksum_url")), checksum_file, limit=MAX_CHECKSUM_BYTES)
        expected = parse_checksum(checksum_file.read_text(encoding="utf-8"))
        _download(_trusted_url(status.get("download_url")), archive, limit=MAX_ARCHIVE_BYTES)
        if not hmac.compare_digest(sha256_file(archive), expected):
            raise WindowsUpdateError("Il controllo di sicurezza SHA-256 non coincide.")
        validate_update_archive(archive)
        with zipfile.ZipFile(archive) as source:
            source.extractall(extracted)
        staged_app = extracted / APP_DIR_NAME
        installer = extracted / "Installa.ps1"
        validate_app(staged_app, version)
        if not installer.is_file():
            raise WindowsUpdateError("Nel pacchetto manca l'installer Windows.")
        return StagedWindowsUpdate(installer, staged_app, version, work_dir)
    except Exception:
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def launch_windows_update(staged: StagedWindowsUpdate, *, parent_pid: int) -> int:
    if sys.platform != "win32":
        raise WindowsUpdateError("L'installazione automatica Windows richiede Windows.")
    wrapper = staged.work_dir / "Applica-Aggiornamento.ps1"
    log = staged.work_dir.parent / "aggiornamento.log"
    wrapper.write_text(
        "param([int]$ParentProcess, [string]$Installer, [string]$WorkDir, [string]$LogPath)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        "  Wait-Process -Id $ParentProcess -ErrorAction SilentlyContinue\n"
        "  & $Installer *>> $LogPath\n"
        "  if ($LASTEXITCODE -ne 0) { throw 'Installer terminato con errore' }\n"
        "  Start-Sleep -Seconds 3\n"
        "  Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue\n"
        "} catch {\n"
        "  ('Aggiornamento non riuscito: ' + $_.Exception.Message) | Out-File -FilePath $LogPath -Append\n"
        "}\n",
        encoding="utf-8",
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(wrapper),
        "-ParentProcess",
        str(parent_pid),
        "-Installer",
        str(staged.installer),
        "-WorkDir",
        str(staged.work_dir),
        "-LogPath",
        str(log),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
    return process.pid
