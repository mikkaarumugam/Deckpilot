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


# Beat counts the Mixxx mapping actually has bindings for. Other values
# raise from the adapter — keeps "loop for 7 beats" from silently snapping
# to 8 the way v0.1 did. Mirror this list in the LLM prompt + the XML
# mapping (mixxx.midi.xml) when extending.
LOOP_BEAT_SIZES = (1, 2, 4, 8, 16, 32)


@dataclass(frozen=True)
class LoopDeck:
    deck: int
    beats: int  # must be one of LOOP_BEAT_SIZES; the adapter validates.


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
class SetFilter:
    """Per-deck single-knob filter (Mixxx QuickEffectRack super1).

    value 0.0 = full low-pass, 0.5 = bypass (no filter), 1.0 = full high-pass.
    One knob covers both filters — matches Pioneer/standard-mixer ergonomics
    and Mixxx's underlying control. See D-022.
    """
    deck: int
    value: float


@dataclass(frozen=True)
class SetFx:
    """Per-deck FX wet for one of Mixxx's two effect units.

    Per-deck routing is achieved by combining the unit's `group_[ChannelN]_enable`
    assignment toggle with the unit's `mix` knob (handled in mixxx.midi.js).
    Caveat: the unit's `mix` is global — setting wet on both decks for the same
    unit shares the value. See D-022 for the trade-off rationale.

    value 0.0 = unit disabled on this deck; >0 = enabled + unit mix=value.
    unit is 1 or 2.
    """
    deck: int
    unit: Literal[1, 2]
    value: float


@dataclass(frozen=True)
class SetPitch:
    """Per-deck pitch slider (Mixxx `rate`, ±8% by default).

    value -1.0 = full down (-8%), 0.0 = no shift, +1.0 = full up (+8%).
    Bipolar scaling is done in the JS handler (CC 64 = neutral).
    """
    deck: int
    value: float


@dataclass(frozen=True)
class LoadTrack:
    """Load a library track onto a deck.

    Not a MIDI action — Mixxx 2.5's controller-script API has no
    path-based load primitive. The adapter raises LoadTrackSuggestion
    carrying the resolved Track; the dashboard renders a suggestion
    card. See DECISIONS § D-015.

    `reasoning` is the LLM's one-line explanation for the pick (BPM
    fit, key compatibility, vibe match). Optional — empty when the
    action comes from regex or a test fixture. Surfaced on the
    suggestion card so the AI's choice is legible, not opaque.
    """
    deck: int
    track_id: int  # library row id from LibraryReader
    reasoning: str = ""


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
    SetFilter,
    SetFx,
    SetPitch,
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
