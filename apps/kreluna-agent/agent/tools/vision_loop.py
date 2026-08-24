"""Vision loop controllato: 1-2 frame, max_steps, BLOCKED su anomalie. Mai 30 FPS."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


class ScreenObservation(BaseModel):
    window_title: str = ""
    elements: list[dict[str, Any]] = Field(default_factory=list)
    extracted_text: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    suggested_targets: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)


class LoopResult(BaseModel):
    status: Literal["done", "blocked", "timeout"]
    steps: int
    observations: list[ScreenObservation] = Field(default_factory=list)
    reason: str = ""


def unexpected_dialog(obs: ScreenObservation) -> bool:
    blob = " ".join(obs.extracted_text + obs.alerts).lower()
    return any(
        word in blob
        for word in ("errore", "password", "unexpected", "avviso di sicurezza", "uac", "account utente")
    )


def run_loop(
    *,
    capture: Callable[[], ScreenObservation],
    act: Callable[[ScreenObservation], str],
    verify: Callable[[ScreenObservation], bool],
    max_steps: int = 8,
    min_confidence: float = 0.45,
) -> LoopResult:
    observations: list[ScreenObservation] = []
    for step in range(1, max_steps + 1):
        obs = capture()
        observations.append(obs)
        if unexpected_dialog(obs):
            return LoopResult(status="blocked", steps=step, observations=observations, reason="UNEXPECTED_DIALOG")
        if obs.confidence < min_confidence:
            return LoopResult(status="blocked", steps=step, observations=observations, reason="LOW_CONFIDENCE")
        if verify(obs):
            return LoopResult(status="done", steps=step, observations=observations, reason="verified")
        act(obs)
    return LoopResult(status="timeout", steps=max_steps, observations=observations, reason="MAX_STEPS")
