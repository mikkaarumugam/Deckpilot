"""
Executor — runs an ActionPlan against an Adapter.

Two responsibilities:
1. Expand any composite/time-based actions (FadeToDeck) into atomic steps
   that the adapter can dispatch directly.
2. Walk the resulting timeline, sleeping between events so each step
   fires at the right wall-clock moment.

The clever bit: after expansion, the executor holds a flat list of
(time, action) pairs sorted by time. It just walks that list. This
handles parallel composition (a fade can overlap with an EQ tweak)
without threading — both events sit in the same timeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from deckpilot.adapters.base import Adapter
from deckpilot.core.actions import (
    ActionPlan,
    DJAction,
    FadeToDeck,
    SetCrossfader,
    TimedAction,
)


# Frame rate for time-based interpolations. 30 updates per second is plenty
# smooth for crossfader fades and keeps MIDI traffic light.
FADE_FPS = 30


@dataclass(frozen=True)
class _AtomicEvent:
    """An atomic action scheduled at an absolute wall-clock offset."""
    at_seconds: float
    action: DJAction  # guaranteed atomic (no FadeToDeck) after expansion


class Executor:
    """Runs ActionPlans through an Adapter, expanding composite steps as needed."""

    def __init__(self, adapter: Adapter) -> None:
        self._adapter = adapter

    # --- public API ---

    def run(self, action: DJAction) -> None:
        """Run a single action by wrapping it in a 1-step plan. Convenience for tests/CLI."""
        self.run_plan(ActionPlan.single(action))

    def run_plan(self, plan: ActionPlan) -> None:
        """Expand the plan into a flat timeline and walk it in real time."""
        timeline = self._expand(plan)
        if not timeline:
            return

        start_monotonic = time.monotonic()
        for event in timeline:
            target = start_monotonic + event.at_seconds
            wait = target - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._adapter.dispatch(event.action)

    # --- expansion ---

    def _expand(self, plan: ActionPlan) -> list[_AtomicEvent]:
        """Replace each FadeToDeck with its constituent SetCrossfader stream."""
        events: list[_AtomicEvent] = []
        for step in plan.steps:
            if isinstance(step.action, FadeToDeck):
                events.extend(self._expand_fade(step))
            else:
                events.append(_AtomicEvent(at_seconds=step.at_seconds, action=step.action))
        # Stable sort by time so simultaneous events keep their declared order.
        events.sort(key=lambda e: e.at_seconds)
        return events

    def _expand_fade(self, step: TimedAction) -> list[_AtomicEvent]:
        """
        Turn one FadeToDeck step into ~30 fps worth of SetCrossfader events,
        each timestamped at `step.at_seconds + offset_within_fade`.

        Assumes the crossfader starts at the opposite end. We don't read Mixxx
        state back — a simplifying assumption that's fine for the demo and
        easy to fix later by querying via MIDI feedback.
        """
        fade = step.action
        assert isinstance(fade, FadeToDeck)

        start_value = 1.0 if fade.deck == 1 else 0.0
        end_value = 0.0 if fade.deck == 1 else 1.0
        total_steps = max(int(fade.seconds * FADE_FPS), 1)
        interval = fade.seconds / total_steps

        events: list[_AtomicEvent] = []
        for i in range(total_steps + 1):
            progress = i / total_steps
            value = start_value + (end_value - start_value) * progress
            events.append(_AtomicEvent(
                at_seconds=step.at_seconds + i * interval,
                action=SetCrossfader(value=value),
            ))
        return events
