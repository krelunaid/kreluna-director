"""Private Webdesk browser, owned by one worker thread, never the desktop pointer.

Opt-in until the installed build has passed the complete Webdesk acceptance test.
No debugging TCP port, personal profile, screenshots, downloads or secret logs.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from agent.tools.browser_command import BrowserCommand
from agent.tools.mac_browser import MacControlError

HOSTS = frozenset({"app.webdesk.it", "www.webdesk.it", "webdesk.it", "sme.genya.it"})


def allowed_url(url: str) -> bool:
    try:
        value = urlsplit(url)
        return (value.scheme == "https" and value.hostname in HOSTS
                and value.port in (None, 443) and not value.username and not value.password)
    except ValueError:
        return False


def profile_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/KrelunaAgent/browser-profiles"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KrelunaAgent/browser-profiles"
    return Path.home() / ".local/share/kreluna-agent/browser-profiles"


class DedicatedRunner:
    dedicated = True

    def __init__(self, page):
        self.page = page

    def osascript(self, command: BrowserCommand) -> str:
        if not isinstance(command, BrowserCommand):
            raise MacControlError("Comando non supportato nel Browser Kreluna.")
        if command.kind not in {"url", "navigate", "evaluate"}:
            raise MacControlError("Comando browser sconosciuto.")
        if command.kind == "navigate" and not allowed_url(command.payload):
            raise MacControlError("Browser Kreluna: indirizzo fuori dai portali Webdesk autorizzati.")
        try:
            if self.page.is_closed():
                raise ValueError("closed")
            if command.kind == "navigate":
                self.page.goto(command.payload, wait_until="domcontentloaded", timeout=30000)
                if not allowed_url(self.page.url):
                    raise ValueError("redirect")
                return "APERTO"
            if not allowed_url(self.page.url):
                raise ValueError("origin")
            if command.kind == "url":
                return self.page.url
            # Recheck in the same JS evaluation, not only before the browser round-trip.
            script = (
                "(() => {if(location.protocol!=='https:' || "
                f"!{json.dumps(sorted(HOSTS))}.includes(location.hostname) || "
                "(location.port && location.port!=='443'))throw new Error('origin');"
                f"return ({command.payload});}})()"
            )
            for attempt in range(3):
                try:
                    result = self.page.evaluate(script)
                    break
                except Exception as exc:
                    if (not command.read_only or attempt == 2
                            or "Execution context was destroyed" not in str(exc)):
                        raise
                    self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            return "" if result is None else str(result)
        except Exception as exc:  # noqa: BLE001 -- Never forward Playwright's message.
            failure = MacControlError(
                "Browser Kreluna: pagina chiusa, cambiata o non disponibile. Operazione fermata."
            )
            failure.diagnostic = (
                "NAVIGATION_IN_PROGRESS" if "Execution context was destroyed" in str(exc)
                else "PAGE_OPERATION_FAILED"
            )
            raise failure from None

    def screencapture(self, path):
        # Login/OTP must never reach task evidence. No whole-desktop capture either.
        raise MacControlError("Acquisizione immagini disattivata nel Browser Kreluna.")


class BrowserService:
    """Keep Playwright on its owning thread, and reject overlapping task execution."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kreluna-browser")
        self.lock = threading.Lock()
        self.playwright = None
        self.context = None
        self.identity = None

    def _context(self, identity):
        if self.context is not None:
            if self.identity != identity:
                raise MacControlError("Browser Kreluna associato a un altro dispositivo: riavvia l'Agent.")
            return self.context
        try:
            from playwright.sync_api import sync_playwright

            bundled = Path(sys.executable).resolve().parents[2] / "browser-runtime"
            if bundled.is_dir():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
            root = profile_root()
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root.chmod(0o700)
            profile = root / hashlib.sha256(identity.encode()).hexdigest()
            profile.mkdir(exist_ok=True, mode=0o700)
            profile.chmod(0o700)
            self.playwright = sync_playwright().start()
            self.context = self.playwright.chromium.launch_persistent_context(
                str(profile), headless=False, chromium_sandbox=True,
                accept_downloads=False, viewport={"width": 1280, "height": 900},
                service_workers="block",
            )
            self.identity = identity
            # Pin the task page; new tabs/popups never silently become the target.
            self.context.on("page", lambda page: page.on("dialog", lambda dialog: dialog.dismiss()))
            self.context.route("**/*", self._route)
            return self.context
        except Exception:  # noqa: BLE001 -- generic installation/launch error, no profile paths.
            if self.playwright is not None:
                self.playwright.stop()
            self.playwright = self.context = None
            raise MacControlError(
                "Browser Kreluna non disponibile. Occorre installare il componente browser dedicato; "
                "Safari e il mouse personale non sono stati utilizzati."
            ) from None

    @staticmethod
    def _route(route):
        request = route.request
        # Block navigation outside the known portals, including redirects and popups.
        if request.is_navigation_request() and not allowed_url(request.url):
            route.abort()
        else:
            route.continue_()

    def run(self, function, kwargs):
        if not self.lock.acquire(blocking=False):
            raise MacControlError("Browser Kreluna già occupato: nessuna seconda richiesta avviata.")
        try:
            return self.executor.submit(self._run, function, kwargs).result()
        finally:
            self.lock.release()

    def _run(self, function, kwargs):
        check = kwargs.get("cancel_check") or (lambda: None)
        check()
        identity = str(kwargs.get("director_url", "")) + "\n" + str(kwargs.get("device_id", ""))
        if not kwargs.get("device_id") or not kwargs.get("director_url"):
            raise MacControlError("Browser Kreluna: dispositivo non associato al Director.")
        context = self._context(identity)
        if len(context.pages) >= 10:
            raise MacControlError("Chiudi le pagine già revisionate nel Browser Kreluna prima di continuare.")
        # Never overwrite an earlier unsaved invoice or the user's active tab.
        page = context.new_page()
        check()
        result = function(**{**kwargs, "runner": DedicatedRunner(page), "supported": lambda: True})
        result["dedicated_browser"] = True
        result["desktop_pointer_used"] = False
        return result

    def close(self):
        def finish():
            if self.context is not None:
                self.context.close()
            if self.playwright is not None:
                self.playwright.stop()
        try:
            self.executor.submit(finish).result(timeout=10)
        except Exception:  # noqa: BLE001, S110 -- shutdown must not print browser state.
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)


_service = None
_service_lock = threading.Lock()


def run_webdesk(function, kwargs):
    global _service
    with _service_lock:
        if _service is None:
            _service = BrowserService()
            atexit.register(_service.close)
    return _service.run(function, kwargs)


def shutdown():
    global _service
    with _service_lock:
        if _service is not None:
            _service.close()
            _service = None
