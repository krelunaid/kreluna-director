from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    w: int
    h: int

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


DESKTOP = Bounds(0, 0, 1920, 1080)
GESTIONALE = Bounds(40, 40, 1200, 800)
