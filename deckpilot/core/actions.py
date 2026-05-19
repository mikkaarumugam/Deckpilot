"""
The DJAction schema — the contract between the parser and the adapter.

Every supported command is one of the dataclasses below. The parser's job is to
turn English into one of these objects. The adapter's job is to turn one of
these objects into MIDI (or whatever the target DJ software speaks).

If you want to add a new action: add a dataclass here, add it to `DJAction`, and
add a handler in the adapter. That's it.

These are filled in for real in M2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union


@dataclass(frozen=True)
class PlayDeck:
    deck: int  # 1 or 2


@dataclass(frozen=True)
class PauseDeck:
    deck: int


@dataclass(frozen=True)
class SetCrossfader:
    value: float  # 0.0 = full left (deck 1), 1.0 = full right (deck 2)


@dataclass(frozen=True)
class FadeToDeck:
    deck: int
    seconds: float


@dataclass(frozen=True)
class LoopDeck:
    deck: int
    beats: int  # 1, 2, 4, 8, 16, 32 — VirtualDJ's loop sizes


@dataclass(frozen=True)
class NudgeDeck:
    deck: int
    direction: Literal["forward", "back"]


# Union type used as the "any supported action" parameter everywhere.
DJAction = Union[PlayDeck, PauseDeck, SetCrossfader, FadeToDeck, LoopDeck, NudgeDeck]
