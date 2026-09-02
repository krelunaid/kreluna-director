from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import plistlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from kreluna_shared.update import is_newer, trusted_release_url

APP_BUNDLE_NAME = "Kreluna Director.app"
BUNDLE_ID = "studio.kreluna.director"
DOWNLOAD_NAME = "Kreluna-Director-Mac.zip"
MAX_ARCHIVE_BYTES = 600 * 1024 * 1024
MAX_EXPANDED_BYTES = 1200 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MAX_ARCHIVE_ENTRIES = 20_000
DEFAULT_DESTINATION = Path("/Applications") / APP_BUNDLE_NAME
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class MacUpdateError(RuntimeError):
    """Errore esplicito e sicuro durante un aggiornamento Mac."""


@dataclass(frozen=True)
class StagedMacUpdate:
    app: Path
    destination: Path
    version: str
    work_dir: Path


def _trusted_url(value: Any) -> str:
    url = trusted_release_url(value)
    if not url:
        raise MacUpdateError("Il collegamento dell'aggiornamento non è attendibile.")
    return url


def _download(url: str, destination: Path, *, limit: int) -> None:
    request = urllib.request.Request(
        _trusted_url(url),
        headers={"User-Agent": "Kreluna-Director-Updater/1"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except Exception as exc:
        raise MacUpdateError("Non riesco a scaricare l'aggiornamento.") from exc
    with response:
        _trusted_url(response.geturl())
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > limit:
            raise MacUpdateError("Il file di aggiornamento è troppo grande.")
        total = 0
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise MacUpdateError("Il file di aggiornamento è troppo grande.")
                output.write(chunk)


def parse_checksum(text: str, filename: str = DOWNLOAD_NAME) -> str:
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts or not SHA256_RE.fullmatch(parts[0]):
            continue
        if len(parts) == 1 or parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    raise MacUpdateError("La firma SHA-256 dell'aggiornamento non è valida.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_info(app: Path) -> dict[str, Any]:
    plist = app / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as source:
            info = plistlib.load(source)
    except Exception as exc:
        raise MacUpdateError("Il pacchetto Mac non contiene informazioni valide.") from exc
    if not isinstance(info, dict):
        raise MacUpdateError("Il pacchetto Mac non contiene informazioni valide.")
    return info


def bundle_version(app: Path) -> str:
    return str(_bundle_info(app).get("CFBundleShortVersionString") or "").strip()


def _validate_symlinks(app: Path) -> None:
    root = app.resolve()
    for item in app.rglob("*"):
        if not item.is_symlink():
            continue
        target = os.readlink(item)
        if os.path.isabs(target):
            raise MacUpdateError("Il pacchetto contiene un collegamento non sicuro.")
        resolved = (item.parent / target).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise MacUpdateError("Il pacchetto contiene un collegamento non sicuro.") from exc


def validate_bundle(app: Path, expected_version: str, *, verify_signature: bool = True) -> None:
    if not app.is_dir() or app.is_symlink():
        raise MacUpdateError("Nel file scaricato manca Kreluna Director.")
    info = _bundle_info(app)
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise MacUpdateError("L'app scaricata non è Kreluna Director.")
    if str(info.get("CFBundleShortVersionString") or "") != expected_version:
        raise MacUpdateError("La versione scaricata non corrisponde all'aggiornamento.")
    required = [
        app / "Contents" / "MacOS" / "Kreluna",
        app / "Contents" / "Resources" / "python-arm64" / "bin" / "python3.12",
        app
        / "Contents"
        / "Resources"
        / "app"
        / "apps"
        / "director-web"
        / "dist"
        / "index.html",
    ]
    if any(not path.is_file() for path in required[:2]) or not required[2].is_file():
        raise MacUpdateError("Il pacchetto scaricato è incompleto.")
    if any(not os.access(path, os.X_OK) for path in required[:2]):
        raise MacUpdateError("Il pacchetto scaricato non può essere avviato.")
    _validate_symlinks(app)
    if verify_signature and sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MacUpdateError("La firma dell'app scaricata non è valida.")


def _extract_archive(archive: Path, destination: Path) -> None:
    if sys.platform != "darwin":
        raise MacUpdateError("L'installazione automatica è disponibile solo su Mac.")
    result = subprocess.run(
        ["/usr/bin/ditto", "-x", "-k", str(archive), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MacUpdateError("Non riesco ad aprire il pacchetto di aggiornamento.")


def validate_update_archive(archive: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise MacUpdateError("Il pacchetto contiene troppi file.")
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
                ):
                    raise MacUpdateError("Il pacchetto contiene un percorso non sicuro.")
                seen.add(name)
                root = path.parts[0]
                if root not in {
                    APP_BUNDLE_NAME,
                    "Applicazioni",
                    "1-SE-DICE-CESTINO.txt",
                    "Apri-me.html",
                    "Disinstalla Kreluna.command",
                    "LEGGIMI-MAC.txt",
                }:
                    raise MacUpdateError("Il pacchetto contiene file non previsti.")
                if root != APP_BUNDLE_NAME and len(path.parts) != 1:
                    raise MacUpdateError("Il pacchetto contiene un percorso non sicuro.")
                expanded += entry.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise MacUpdateError("Il pacchetto estratto è troppo grande.")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    target = source.read(entry).decode("utf-8", errors="strict")
                    if name == APP_BUNDLE_NAME:
                        raise MacUpdateError("Il pacchetto contiene un collegamento non sicuro.")
                    if name == "Applicazioni" and target == "/Applications":
                        continue
                    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                    if target.startswith("/") or not normalized.startswith(f"{APP_BUNDLE_NAME}/"):
                        raise MacUpdateError("Il pacchetto contiene un collegamento non sicuro.")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise MacUpdateError("Il file di aggiornamento non è uno ZIP valido.") from exc


def _require_installed_app(app: Path) -> Path:
    resolved = app.resolve()
    if resolved != DEFAULT_DESTINATION or app.name != APP_BUNDLE_NAME:
        raise MacUpdateError("Sposta prima Kreluna Director nella cartella Applicazioni.")
    if not app.is_dir():
        raise MacUpdateError("Kreluna Director non risulta installata in Applicazioni.")
    if not os.access(app.parent, os.W_OK):
        raise MacUpdateError("Non ho il permesso di aggiornare la cartella Applicazioni.")
    return resolved


def stage_macos_update(
    status: dict[str, Any],
    *,
    current_app: Path,
    support_dir: Path,
) -> StagedMacUpdate:
    version = str(status.get("latest_version") or "").strip()
    if status.get("available") is not True or not version:
        raise MacUpdateError("Non ci sono aggiornamenti da installare.")
    destination = _require_installed_app(current_app)
    current_version = bundle_version(destination)
    if not is_newer(version, current_version):
        raise MacUpdateError("Non ci sono aggiornamenti da installare.")
    if str(status.get("platform") or "") != "macos":
        raise MacUpdateError("Questo pacchetto non è destinato al Mac.")
    download_url = _trusted_url(status.get("download_url"))
    checksum_url = _trusted_url(status.get("checksum_url"))

    updates = support_dir / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    os.chmod(updates, 0o700)
    work_dir = Path(tempfile.mkdtemp(prefix="kreluna-update-", dir=updates))
    archive = work_dir / DOWNLOAD_NAME
    checksum_file = work_dir / f"{DOWNLOAD_NAME}.sha256"
    extracted = work_dir / "estratto"
    extracted.mkdir()
    try:
        _download(checksum_url, checksum_file, limit=MAX_CHECKSUM_BYTES)
        expected = parse_checksum(checksum_file.read_text(encoding="utf-8"))
        _download(download_url, archive, limit=MAX_ARCHIVE_BYTES)
        if not hmac.compare_digest(sha256_file(archive), expected):
            raise MacUpdateError("Il controllo di sicurezza SHA-256 non coincide.")
        validate_update_archive(archive)
        _extract_archive(archive, extracted)
        staged_app = extracted / APP_BUNDLE_NAME
        validate_bundle(staged_app, version)
        return StagedMacUpdate(staged_app, destination, version, work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def launch_macos_update(staged: StagedMacUpdate, *, parent_pid: int) -> int:
    log = staged.work_dir.parent / "aggiornamento.log"
    command = [
        sys.executable,
        "-m",
        "kreluna_shared.macos_update",
        "apply",
        "--staged-app",
        str(staged.app),
        "--destination",
        str(staged.destination),
        "--version",
        staged.version,
        "--parent-pid",
        str(parent_pid),
    ]
    with log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    return process.pid


def _wait_for_exit(pid: int, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise MacUpdateError("Non riesco a chiudere la versione precedente.") from exc
        time.sleep(0.2)
    raise MacUpdateError("La versione precedente non si è chiusa in tempo.")


def _safe_remove_managed_app(path: Path) -> None:
    allowed = path.parent == DEFAULT_DESTINATION.parent and path.name.startswith(
        ".Kreluna Director.app."
    )
    if not allowed:
        raise MacUpdateError("Rifiutata la pulizia di un percorso non gestito.")
    if path.exists():
        shutil.rmtree(path)


def _wait_for_version(version: str, timeout: float = 150) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1) as response:
                body = json.loads(response.read().decode("utf-8"))
            if body.get("service") == "director-api" and body.get("version") == version:
                return True
        except (OSError, ValueError):
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return False


def _cleanup_staging(staged_app: Path) -> None:
    work_dir = staged_app.parent.parent
    configured = os.environ.get("KRELUNA_SUPPORT_DIR")
    if not configured:
        return
    expected_parent = (Path(configured) / "updates").resolve()
    if (
        work_dir.parent.resolve() == expected_parent
        and work_dir.name.startswith("kreluna-update-")
        and staged_app.parent.name == "estratto"
    ):
        shutil.rmtree(work_dir, ignore_errors=True)


def apply_staged_update(
    staged_app: Path,
    destination: Path,
    version: str,
    parent_pid: int,
) -> None:
    destination = _require_installed_app(destination)
    _wait_for_exit(parent_pid)
    validate_bundle(staged_app, version)
    suffix = f"{os.getpid()}"
    incoming = destination.parent / f".{APP_BUNDLE_NAME}.incoming-{suffix}"
    backup = destination.parent / f".{APP_BUNDLE_NAME}.backup-{suffix}"
    _safe_remove_managed_app(incoming)
    _safe_remove_managed_app(backup)

    copied = subprocess.run(
        ["/usr/bin/ditto", str(staged_app), str(incoming)],
        capture_output=True,
        text=True,
        check=False,
    )
    if copied.returncode != 0:
        raise MacUpdateError("Non riesco a copiare l'aggiornamento in Applicazioni.")
    subprocess.run(["/usr/bin/xattr", "-cr", str(incoming)], check=False)
    validate_bundle(incoming, version)

    os.replace(destination, backup)
    try:
        os.replace(incoming, destination)
    except Exception:
        os.replace(backup, destination)
        raise

    launcher = destination / "Contents" / "MacOS" / "Kreluna"
    process = subprocess.Popen(
        [str(launcher)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    if _wait_for_version(version):
        _safe_remove_managed_app(backup)
        _cleanup_staging(staged_app)
        return

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    failed = destination.parent / f".{APP_BUNDLE_NAME}.failed-{suffix}"
    _safe_remove_managed_app(failed)
    os.replace(destination, failed)
    os.replace(backup, destination)
    _safe_remove_managed_app(failed)
    subprocess.Popen(
        ["/usr/bin/open", str(destination)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    raise MacUpdateError("La nuova versione non è partita: ho ripristinato quella precedente.")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--staged-app", type=Path, required=True)
    apply_parser.add_argument("--destination", type=Path, required=True)
    apply_parser.add_argument("--version", required=True)
    apply_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        apply_staged_update(
            args.staged_app,
            args.destination,
            args.version,
            args.parent_pid,
        )
    except (MacUpdateError, OSError, subprocess.SubprocessError) as exc:
        print(f"Aggiornamento non riuscito: {exc}", file=sys.stderr)
        if args.destination == DEFAULT_DESTINATION and args.destination.is_dir():
            subprocess.Popen(
                ["/usr/bin/open", str(args.destination)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
