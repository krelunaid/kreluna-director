"""Small compatibility shim required by pywebview's deprecated constants."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class module_property:
    """Resolve a decorated zero-argument function whenever its value is used."""

    def __init__(self, getter: Callable[[], Any]) -> None:
        self._getter = getter
        self.__name__ = getter.__name__

    def _value(self) -> Any:
        return self._getter()

    def __repr__(self) -> str:
        return repr(self._value())

    def __str__(self) -> str:
        return str(self._value())

    def __bool__(self) -> bool:
        return bool(self._value())

    def __int__(self) -> int:
        return int(self._value())

    def __index__(self) -> int:
        return int(self._value())

    def __hash__(self) -> int:
        return hash(self._value())

    def __eq__(self, other: object) -> bool:
        return bool(self._value() == other)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._value(), name)
