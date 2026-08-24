"""Memoria corta della chat: cosa il Director ha appena chiesto, e a chi.

Serve perché "5000 euro" dopo "manca l'importo" sia una risposta, non una
richiesta nuova. Dura pochi minuti e sta in memoria: non è uno storico.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.models import utcnow

TTL = timedelta(minutes=10)


@dataclass
class Waiting:
    pending: dict[str, Any]
    asked_at: Any


class FollowUps:
    def __init__(self) -> None:
        self._by_user: dict[str, Waiting] = {}

    def remember(self, user_id: str, pending: dict[str, Any]) -> None:
        self._by_user[user_id] = Waiting(pending=pending, asked_at=utcnow())

    def take(self, user_id: str) -> dict[str, Any] | None:
        waiting = self._by_user.get(user_id)
        if waiting is None:
            return None
        if utcnow() - waiting.asked_at > TTL:
            self.forget(user_id)
            return None
        return waiting.pending

    def forget(self, user_id: str) -> None:
        self._by_user.pop(user_id, None)


followups = FollowUps()
