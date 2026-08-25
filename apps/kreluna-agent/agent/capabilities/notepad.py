from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable

from kreluna_shared.crypto import sha256_hex

from agent.tools.render import render_card


def write_notepad(
    text: str,
    cancel_check: Callable[[], None] | None = None,
    register_process: Callable[[subprocess.Popen], None] | None = None,
) -> dict:
    check = cancel_check or (lambda: None)
    check()
    used = "virtual"
    if os.name == "nt":
        try:
            used = _windows_notepad(
                text,
                cancel_check=check,
                register_process=register_process,
            )
        except PermissionError:
            raise
        except Exception:
            used = "virtual_fallback"
    check()
    image = render_card(
        "KRELUNA — Blocco note controllato",
        [
            "Capability: notepad_write",
            f"Metodo: {used}",
            "",
            "Testo:",
            text,
            "",
            "Nessun file è stato salvato sul disco utente.",
        ],
    )
    return {
        "ok": True,
        "text": text,
        "method": used,
        "evidence": [
            {
                "kind": "screenshot",
                "sha256": sha256_hex(image),
                "png": image,
                "metadata": {"window": "Kreluna Notepad", "method": used},
            }
        ],
    }


def _windows_notepad(
    text: str,
    *,
    cancel_check: Callable[[], None],
    register_process: Callable[[subprocess.Popen], None] | None = None,
) -> str:
    cancel_check()
    process = subprocess.Popen(["notepad.exe"])
    if register_process is not None:
        register_process(process)
    time.sleep(1)
    cancel_check()
    from pywinauto import Application

    app = Application(backend="uia").connect(path="notepad.exe")
    win = app.top_window()
    edit = win.child_window(control_type="Edit")
    edit.set_focus()
    cancel_check()
    edit.type_keys(text, with_spaces=True)
    return "windows_notepad"
