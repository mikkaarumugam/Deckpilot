"""
Executor — runs DJActions against an Adapter.

For atomic actions (Play, Pause, SetCrossfader, Loop, Nudge) the Executor
just hands them straight to the adapter. The interesting case is the
composite/time-based action: FadeToDeck. The executor expands it into a
stream of SetCrossfader calls spaced over the requested duration.

Why this separation:
- The adapter only knows how to send one MIDI primitive at a time. It doesn't
  loop, sleep, or know that a "fade" is multiple crossfader moves.
- Adding a new time-based action later (e.g. "ramp tempo to X over Y beats")
  goes here, not in the adapter. The adapter stays small.
"""

from __future__ import annotations

import time

from deckpilot.adapters.base import Adapter
from deckpilot.core.actions import DJAction, FadeToDeck, SetCrossfader


# Frame rate for time-based interpolations. 30 updates per second is plenty
# smooth for crossfader fades and keeps the MIDI traffic light.
FADE_FPS = 30


class Executor:
    """Runs DJActions through an Adapter, expanding composite actions as needed."""

    def __init__(self, adapter: Adapter) -> None:
        self._adapter = adapter

    def run(self, action: DJAction) -> None:
        if isinstance(action, FadeToDeck):
            self._run_fade(action)
        else:
            # Everything else is atomic — pass straight through.
            self._adapter.dispatch(action)

    def _run_fade(self, action: FadeToDeck) -> None:
        """
        Smoothly slide the crossfader to the target deck over `seconds`.

        Assumes the crossfader starts at the OPPOSITE end (i.e. if you're
        fading to deck 2, the crossfader is currently fully on deck 1).
        We don't read Mixxx's state back, so this is a simplifying assumption
        — fine for the demo, would need state read-back for production.
        """
        start = 1.0 if action.deck == 1 else 0.0  # opposite end
        end = 0.0 if action.deck == 1 else 1.0    # target end

        # How many crossfader updates we'll send. At minimum 1 so we always
        # land on the target value.
        total_steps = max(int(action.seconds * FADE_FPS), 1)
        interval = action.seconds / total_steps

        for step in range(total_steps + 1):
            progress = step / total_steps  # 0.0 → 1.0
            value = start + (end - start) * progress
            self._adapter.dispatch(SetCrossfader(value=value))
            # Don't sleep after the final move — we're done.
            if step < total_steps:
                time.sleep(interval)
