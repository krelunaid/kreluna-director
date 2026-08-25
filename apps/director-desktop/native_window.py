"""Native application window for packaged Kreluna Director builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


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
    local_url = validated_local_url(url)
    if sys.platform == "darwin":
        executable = mac_window_executable()
        if not executable.is_file():
            raise RuntimeError("La finestra nativa di Kreluna è mancante: reinstalla l'app")
        subprocess.run([str(executable), local_url], check=True)
        return
    if sys.platform == "win32":
        _run_windows_window(local_url, storage_path=storage_path)
        return
    raise RuntimeError("La finestra nativa non è disponibile su questo sistema")


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
