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
- ONLY two trigger types. Beat-aware triggers (e.g. "in 8 bars") would
  need beat-grid read-back; deferred to v0.3.
- No recovery / re-planning. If the LLM emits a schedule with bad
  assumptions (wrong track BPM, etc.), the user cancels and re-prompts.
- No nesting. A ScheduledPlan's plan is a flat ActionPlan, not another
  schedule. Keep the model dumb for now.
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

    def fires(self, _state: "MixxxState") -> bool:
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

    def fires(self, state: "MixxxState") -> bool:
        return state.deck(self.deck).position >= self.at

    def describe(self) -> str:
        # Round to whole percent for legibility in the UI.
        return f"deck {self.deck} reaches {int(self.at * 100)}%"


Trigger = Union[Immediate, DeckPosition]


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
