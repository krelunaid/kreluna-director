from __future__ import annotations

import asyncio


class SafetyState:
    def __init__(self) -> None:
        self.killed = False
        self.paused = False
        self.gui_lock = asyncio.Lock()
        self.active_task_id: str | None = None

    def assert_not_killed(self) -> None:
        if self.killed:
            raise PermissionError("AGENT_KILLED")
        if self.paused:
            raise PermissionError("AGENT_PAUSED")
