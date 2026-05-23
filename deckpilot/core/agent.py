"""
Agent layer (demo-scoped Tier 2) — goal-directed plans with triggers.

The execution model today (ActionPlan) is: "run these timed steps on a
wall-clock timeline NOW." That's great for one-shot commands, but a DJ
goal looks more like: "do X now. Then when Y happens, do Z."

This module models that shape:

  AgentSchedule
    = a list of ScheduledPlans
        each ScheduledPlan
        = (Trigger, ActionPlan, label)

  Trigger
    = Immediate          (fires right away)
    | DeckPosition       (fires when deck N's playhead crosses fraction X)

The scheduler (in backend/services/agent_runtime.py) walks pending
ScheduledPlans, checks each step's trigger against the live Mixxx
state, and runs the plan when the condition fires.

Demo-scope decisions:
- THREE trigger types now (Immediate, DeckPosition, AfterBeats — D-023
  added beat-aware. Recovery / re-planning + nesting still parked.)
- No recovery / re-planning. If the LLM emits a schedule with bad
  assumptions (wrong track BPM, etc.), the user cancels and re-prompts.
- No nesting. A ScheduledPlan's plan is a flat ActionPlan, not another
  schedule. Keep the model dumb for now.

Trigger interface:
  fires(state, baseline=None) -> bool
where `state` is the live MixxxState snapshot and `baseline` is the
state captured the first time this step's trigger was checked. Stateful
triggers (AfterBeats) use the baseline to compute deltas; stateless
triggers (Immediate, DeckPosition) accept and ignore it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from .actions import ActionPlan

if TYPE_CHECKING:
    from deckpilot.adapters.midi_feedback import MixxxState


# ── Trigger types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Immediate:
    """Fires the moment the schedule starts. Used for the kickoff step."""

    def fires(
        self,
        _state: "MixxxState",
        _baseline: "MixxxState | None" = None,
    ) -> bool:
        return True

    def describe(self) -> str:
        return "now"


@dataclass(frozen=True)
class DeckPosition:
    """Fires when the given deck's playhead crosses `at` (0.0..1.0).

    `at=0.92` is the canonical "near end" — leaves ~8% of the track
    for the transition to complete before the outgoing track silences.
    """

    deck: int
    at: float

    def fires(
        self,
        state: "MixxxState",
        _baseline: "MixxxState | None" = None,
    ) -> bool:
        return state.deck(self.deck).position >= self.at

    def describe(self) -> str:
        # Round to whole percent for legibility in the UI.
        return f"deck {self.deck} reaches {int(self.at * 100)}%"


@dataclass(frozen=True)
class AfterBeats:
    """Fires `count` beats after this step became pending (D-023).

    Stateful in the sense that "5 beats from now" needs a starting
    point. The runtime captures a MixxxState baseline the first time
    this trigger is checked and passes it back in on every poll; the
    trigger itself stays a frozen dataclass.

    deck:  which deck's beats to count (1 or 2). Mixxx only fires
           `beat_active` while a track is playing on that deck — if
           the deck pauses mid-wait, the count pauses with it. That's
           the right behaviour for "in 4 beats" intents: count to 4
           musical beats, not 4 seconds.
    count: number of beats to wait. ≥1.
    """

    deck: int
    count: int

    def fires(
        self,
        state: "MixxxState",
        baseline: "MixxxState | None" = None,
    ) -> bool:
        # Without a baseline we can't compute the delta. The runtime
        # always provides one in practice; the None case is a
        # belt-and-suspenders guard for unit tests / mis-use.
        if baseline is None:
            return False
        elapsed = state.deck(self.deck).beat_count - baseline.deck(self.deck).beat_count
        return elapsed >= self.count

    def describe(self) -> str:
        return f"deck {self.deck} reaches +{self.count} beats"


Trigger = Union[Immediate, DeckPosition, AfterBeats]


# ── Schedule shapes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduledPlan:
    """One entry in an AgentSchedule: a plan waiting on a trigger.

    `label` is a one-line human-readable description for the UI queue
    ("transition into highjack", "fade out"). Comes from the LLM.
    """

    trigger: Trigger
    plan: ActionPlan
    label: str


@dataclass(frozen=True)
class AgentSchedule:
    """An ordered sequence of ScheduledPlans. The agent runtime walks
    them in order — each plan must fire (or be skipped) before the
    next one's trigger is even checked. Keeps semantics simple: no
    out-of-order execution, no parallel branches."""

    steps: tuple[ScheduledPlan, ...]

    @property
    def is_empty(self) -> bool:
        return not self.steps
