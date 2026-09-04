"""Typed browser commands: never translate arbitrary AppleScript into JavaScript."""

from dataclasses import dataclass

DEDICATED = "Browser Kreluna"


@dataclass(frozen=True, repr=False)
class BrowserCommand:
    kind: str
    payload: str = ""
    read_only: bool = False

    def __repr__(self):
        # A command can contain a password or a one-time code.
        return f"BrowserCommand({self.kind!r}, <redacted>)"
