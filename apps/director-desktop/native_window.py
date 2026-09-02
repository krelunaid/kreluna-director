"""Native application window for packaged Kreluna Director builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

_native_window_process: subprocess.Popen | None = None


def validated_local_url(value: str) -> str:
    """Keep the native shell bound to the local Director and nothing else."""

    url = value.strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.port != 8080
    ):
        raise ValueError("La finestra Kreluna può aprire soltanto il Director locale")
    return url


def mac_window_executable() -> Path:
    configured = os.environ.get("KRELUNA_NATIVE_WINDOW", "").strip()
    if configured:
        return Path(configured)
    executable = Path(sys.executable).resolve()
    try:
        contents = executable.parents[3]
    except IndexError:
        return Path()
    return contents / "MacOS" / "KrelunaWindow"


def run_native_window(url: str, *, storage_path: Path) -> None:
    global _native_window_process
    local_url = validated_local_url(url)
    if sys.platform == "darwin":
        executable = mac_window_executable()
        if not executable.is_file():
            raise RuntimeError("La finestra nativa di Kreluna è mancante: reinstalla l'app")
        process = subprocess.Popen([str(executable), local_url])
        _native_window_process = process
        try:
            if process.wait() != 0:
                raise subprocess.CalledProcessError(process.returncode, process.args)
        finally:
            if _native_window_process is process:
                _native_window_process = None
        return
    if sys.platform == "win32":
        _run_windows_window(local_url, storage_path=storage_path)
        return
    raise RuntimeError("La finestra nativa non è disponibile su questo sistema")


def terminate_native_window() -> None:
    """Chiude l'helper Mac appartenente a questo Director prima del riavvio."""

    process = _native_window_process
    if process is not None and process.poll() is None:
        process.terminate()


def activate_existing_mac_window(url: str) -> bool:
    """Porta davanti la finestra già aperta senza crearne una seconda."""

    if sys.platform != "darwin":
        return False
    local_url = validated_local_url(url)
    executable = mac_window_executable()
    if not executable.is_file():
        return False
    found = subprocess.run(
        ["/usr/bin/pgrep", "-f", f"^{executable} {local_url}$"],
        capture_output=True,
        text=True,
        check=False,
    )
    first = found.stdout.strip().splitlines()[:1]
    if found.returncode != 0 or not first or not first[0].isdigit():
        return False
    script = (
        "on run argv\n"
        "tell application \"System Events\" to set frontmost of first process whose unix id is "
        "(item 1 of argv as integer) to true\n"
        "end run"
    )
    activated = subprocess.run(
        ["/usr/bin/osascript", "-e", script, first[0]],
        capture_output=True,
        check=False,
    )
    return activated.returncode == 0


def _run_windows_window(url: str, *, storage_path: Path) -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("La finestra nativa di Kreluna è mancante: reinstalla il programma") from exc

    storage_path.mkdir(parents=True, exist_ok=True)
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        "Kreluna Director",
        url,
        width=1440,
        height=900,
        min_size=(1100, 700),
        resizable=True,
        background_color="#07101f",
        text_select=True,
        zoomable=False,
    )
    try:
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(storage_path),
        )
    except Exception as exc:
        raise RuntimeError(
            "Kreluna richiede Microsoft Edge WebView2. Aggiorna Windows e reinstalla Kreluna."
        ) from exc
