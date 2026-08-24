"""Toolkit automazione: API -> UI names -> Playwright/DOM -> mouse in bounds."""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from agent.tools.bounds import Bounds, GESTIONALE

Method = Literal["api", "ui_automation", "playwright", "mouse"]


class ToolSpec(BaseModel):
    name: str
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    method: Method
    allowlisted: bool = True


class AutomationError(PermissionError):
    pass


def prefer_method(available: list[Method]) -> Method:
    order: list[Method] = ["api", "ui_automation", "playwright", "mouse"]
    for method in order:
        if method in available:
            return method
    raise AutomationError("NO_ALLOWED_METHOD")


def safe_click(x: int, y: int, bounds: Bounds = GESTIONALE) -> dict[str, Any]:
    if not bounds.contains(x, y):
        raise AutomationError("OUTSIDE_ALLOWED_REGION")
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.moveTo(x, y, duration=0.15)
        pyautogui.click(x, y)
        return {"ok": True, "method": "mouse", "x": x, "y": y, "visible": True}
    except ImportError:
        return {
            "ok": True,
            "method": "mouse_simulated",
            "x": x,
            "y": y,
            "visible": False,
            "note": "pyautogui assente: click registrato, non eseguito su questo OS.",
        }


def click_named_control(title: str | None = None, auto_id: str | None = None) -> dict[str, Any]:
    if not title and not auto_id:
        raise AutomationError("CONTROL_NOT_NAMED")
    try:
        from pywinauto import Application

        app = Application(backend="uia").connect(title_re=".*")
        win = app.top_window()
        spec = win.child_window(title=title, auto_id=auto_id)
        spec.wait("exists enabled visible ready", timeout=10)
        spec.click_input()
        return {"ok": True, "method": "ui_automation", "title": title, "auto_id": auto_id}
    except Exception as exc:
        return {"ok": False, "method": "ui_automation", "error": str(exc)[:200]}


def run_allowlisted(name: str, handlers: dict[str, Callable[..., Any]], **kwargs: Any) -> Any:
    handler = handlers.get(name)
    if handler is None:
        raise AutomationError("CAPABILITY_NOT_ALLOWED")
    return handler(**kwargs)
