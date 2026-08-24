from __future__ import annotations

import os
import subprocess
import time

from kreluna_shared.crypto import sha256_hex

from agent.tools.render import render_card


def write_notepad(text: str) -> dict:
    used = "virtual"
    if os.name == "nt":
        try:
            used = _windows_notepad(text)
        except Exception:
            used = "virtual_fallback"
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


def _windows_notepad(text: str) -> str:
    subprocess.Popen(["notepad.exe"])
    time.sleep(1)
    from pywinauto import Application

    app = Application(backend="uia").connect(path="notepad.exe")
    win = app.top_window()
    edit = win.child_window(control_type="Edit")
    edit.set_focus()
    edit.type_keys(text, with_spaces=True)
    return "windows_notepad"
