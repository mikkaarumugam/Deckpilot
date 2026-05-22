"""
DJAction schema — the contract between the parser and the adapter.

There are two layers here:

1. ATOMIC actions (the dataclasses Play/Pause/SetCrossfader/Loop/Nudge/SetEQ/
   SetVolume/HotCue/Sync/FadeToDeck). One atomic action → one or more MIDI
   messages from the adapter (or, in FadeToDeck's case, a series of them
   from the executor).

2. ActionPlan — a sequence of TimedAction wrapping atomic actions with
   timing. This is what the parser actually produces. A single-action
   command like "play deck 1" becomes a 1-step plan; a multi-step command
   like "bass swap into deck 2" becomes a multi-step plan.

The parser always returns an ActionPlan. The executor walks the plan,
firing each action at its scheduled time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


# --- Atomic actions ---

@dataclass(frozen=True)
class PlayDeck:
    deck: int


@dataclass(frozen=True)
class PauseDeck:
    deck: int


@dataclass(frozen=True)
class SetCrossfader:
    value: float  # 0.0 = full deck 1, 1.0 = full deck 2


@dataclass(frozen=True)
class FadeToDeck:
    """Composite action — the executor expands it into a SetCrossfader stream."""
    deck: int
    seconds: float


@dataclass(frozen=True)
class LoopDeck:
    deck: int
    beats: int  # currently always treated as 8 by the Mixxx mapping (v0.1 limitation)


@dataclass(frozen=True)
class NudgeDeck:
    deck: int
    direction: Literal["forward", "back"]


@dataclass(frozen=True)
class SetEQ:
    """Set one of three EQ bands on a deck. value 0.0 = full cut, 1.0 = neutral."""
    deck: int
    band: Literal["low", "mid", "high"]
    value: float


@dataclass(frozen=True)
class SetVolume:
    """Channel fader on a deck. value 0.0 = silent, 1.0 = full."""
    deck: int
    value: float


@dataclass(frozen=True)
class HotCue:
    """Jump to (or set) a hot cue. cue is 1..8."""
    deck: int
    cue: int


@dataclass(frozen=True)
class Sync:
    """Trigger Mixxx's beatsync — match BPM + beat alignment to the other deck."""
    deck: int


@dataclass(frozen=True)
class LoadTrack:
    """Load a library track onto a deck.

    Not a MIDI action — Mixxx 2.5's controller-script API has no
    path-based load primitive. The adapter dispatches this via
    `open -a Mixxx <file>`, which macOS routes to the running Mixxx
    instance. Mixxx loads the file to its focus deck; if that doesn't
    match `self.deck`, the user can click the target deck once before
    re-issuing. See DECISIONS § D-015.
    """
    deck: int
    track_id: int  # library row id from LibraryReader


# Union of every atomic action type.
DJAction = Union[
    PlayDeck,
    PauseDeck,
    SetCrossfader,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    SetEQ,
    SetVolume,
    HotCue,
    Sync,
    LoadTrack,
]


# --- Plan layer ---

@dataclass(frozen=True)
class TimedAction:
    """One action scheduled at a specific time within a plan."""
    action: DJAction
    at_seconds: float = 0.0  # absolute time from plan start


@dataclass(frozen=True)
class ActionPlan:
    """A sequence of timed actions. The executor walks these in order."""
    steps: tuple[TimedAction, ...] = field(default_factory=tuple)

    @classmethod
    def single(cls, action: DJAction) -> "ActionPlan":
        """Convenience: wrap one action in a 1-step plan at t=0."""
        return cls(steps=(TimedAction(action=action, at_seconds=0.0),))
