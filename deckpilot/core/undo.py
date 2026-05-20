"""
Compute the inverse of an ActionPlan so the dashboard's "↶ Undo" button
can reverse a previous command.

Design notes:
- For single actions with an obvious inverse (Play ↔ Pause, SetEQ → neutral),
  we just emit the inverse.
- For multi-step plans (bass swap), we reverse the step order AND invert
  each atomic step. We collapse all `at_seconds` back to 0 so the undo runs
  immediately — replaying the timing of the original would mean a 4-second
  undo for a 4-second action, which is bad UX.
- Some actions are not reversible (HotCue jump, Sync — these don't have
  natural inverses). We omit them from the undo plan. If a plan consists
  entirely of non-reversible actions, return None.
"""

from __future__ import annotations

from deckpilot.core.actions import (
    ActionPlan,
    DJAction,
    FadeToDeck,
    HotCue,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetVolume,
    Sync,
    TimedAction,
)


# "Neutral" defaults — what we snap to when undoing a change without
# remembering the previous value. Not perfect, but predictable for a demo.
NEUTRAL_EQ = 1.0          # Mixxx EQ: 1.0 = unity (no boost/cut)
NEUTRAL_VOLUME = 1.0      # full
NEUTRAL_CROSSFADER = 0.5  # center


def inverse_action(action: DJAction) -> DJAction | None:
    """Return the inverse of a single action, or None if it can't be undone."""
    if isinstance(action, PlayDeck):
        return PauseDeck(deck=action.deck)
    if isinstance(action, PauseDeck):
        return PlayDeck(deck=action.deck)
    if isinstance(action, SetCrossfader):
        return SetCrossfader(value=NEUTRAL_CROSSFADER)
    if isinstance(action, FadeToDeck):
        # Snap back to the opposite deck (i.e. where the fade started).
        # We use a quick fade rather than instant so it sounds smooth.
        return FadeToDeck(deck=(2 if action.deck == 1 else 1), seconds=1.0)
    if isinstance(action, LoopDeck):
        # Loops in Mixxx are toggles — firing the same trigger turns them off.
        return LoopDeck(deck=action.deck, beats=action.beats)
    if isinstance(action, SetEQ):
        return SetEQ(deck=action.deck, band=action.band, value=NEUTRAL_EQ)
    if isinstance(action, SetVolume):
        return SetVolume(deck=action.deck, value=NEUTRAL_VOLUME)
    # NudgeDeck, HotCue, Sync are transient/stateful in ways we can't cleanly
    # undo without tracking prior state. Return None to skip them.
    if isinstance(action, (NudgeDeck, HotCue, Sync)):
        return None
    return None


def inverse_plan(plan: ActionPlan) -> ActionPlan | None:
    """
    Inverse the whole plan: reverse the order, invert each step, drop the
    timing (run undo immediately rather than replaying the original duration).
    """
    inverted: list[TimedAction] = []
    for step in reversed(plan.steps):
        inv = inverse_action(step.action)
        if inv is not None:
            inverted.append(TimedAction(action=inv, at_seconds=0.0))
    if not inverted:
        return None
    return ActionPlan(steps=tuple(inverted))
