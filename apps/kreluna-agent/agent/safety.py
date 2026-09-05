from __future__ import annotations

import asyncio
import subprocess
import threading


class SafetyState:
    def __init__(self) -> None:
        self.killed = False
        self.paused = False
        self.remote_active = False
        self.workers = 0
        self.gui_lock = asyncio.Lock()
        self.active_task_id: str | None = None
        self.cancelled_tasks: set[str] = set()
        self._owned_processes: set[subprocess.Popen] = set()
        self._process_lock = threading.Lock()

    def assert_not_killed(self) -> None:
        if self.remote_active:
            raise PermissionError("Assistenza remota attiva: nessuna automazione consentita")
        if self.killed:
            raise PermissionError("AGENT_KILLED")
        if self.paused:
            raise PermissionError("AGENT_PAUSED")

    def assert_task_active(self, task_id: str) -> None:
        self.assert_not_killed()
        if task_id in self.cancelled_tasks:
            raise PermissionError("TASK_CANCELLED")

    def begin_task(self, task_id: str) -> None:
        self.cancelled_tasks.discard(task_id)
        self.active_task_id = task_id

    def finish_task(self, task_id: str) -> None:
        if self.active_task_id == task_id:
            self.active_task_id = None

    def register_process(self, process: subprocess.Popen) -> None:
        with self._process_lock:
            self._owned_processes.add(process)

    def _terminate_owned_processes(self) -> None:
        with self._process_lock:
            processes = list(self._owned_processes)
            self._owned_processes.clear()
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                process.terminate()
            except OSError:
                continue

    def kill(self) -> None:
        self.killed = True
        self.paused = True
        self._terminate_owned_processes()

    def pause(self) -> None:
        self.paused = True
        self._terminate_owned_processes()

    def resume(self) -> None:
        self.killed = False
        self.paused = False

    def cancel_task(self, task_id: str) -> None:
        self.cancelled_tasks.add(task_id)
        self._terminate_owned_processes()
