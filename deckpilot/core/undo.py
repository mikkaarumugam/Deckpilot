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
    SetFilter,
    SetFx,
    SetPitch,
    SetVolume,
    Sync,
    TimedAction,
)


# "Neutral" defaults — what we snap to when undoing a change without
# remembering the previous value. Not perfect, but predictable for a demo.
NEUTRAL_EQ = 1.0          # Mixxx EQ: 1.0 = unity (no boost/cut)
NEUTRAL_VOLUME = 1.0      # full
NEUTRAL_CROSSFADER = 0.5  # center
NEUTRAL_FILTER = 0.5      # bypass (Pioneer-style single-knob center)
NEUTRAL_FX = 0.0          # FX off / unit not routed to this deck
NEUTRAL_PITCH = 0.0       # no pitch shift


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
    if isinstance(action, SetFilter):
        return SetFilter(deck=action.deck, value=NEUTRAL_FILTER)
    if isinstance(action, SetFx):
        return SetFx(deck=action.deck, unit=action.unit, value=NEUTRAL_FX)
    if isinstance(action, SetPitch):
        return SetPitch(deck=action.deck, value=NEUTRAL_PITCH)
    # NudgeDeck, HotCue, Sync are transient/stateful in ways we can't cleanly
    # undo without tracking prior state. Return None to skip them.
    if isinstance(action, (NudgeDeck, HotCue, Sync)):
        return None
    return None


def reset_plan() -> ActionPlan:
    """
    Return a 'go to known-good state' plan: pause both decks, crossfader to
    center, all EQs to neutral, volumes to full. Useful as a panic button
    when the system gets into a weird state mid-set.
    """
    steps: list[TimedAction] = [
        TimedAction(action=PauseDeck(deck=1), at_seconds=0.0),
        TimedAction(action=PauseDeck(deck=2), at_seconds=0.0),
        TimedAction(action=SetCrossfader(value=NEUTRAL_CROSSFADER), at_seconds=0.0),
        TimedAction(action=SetVolume(deck=1, value=NEUTRAL_VOLUME), at_seconds=0.0),
        TimedAction(action=SetVolume(deck=2, value=NEUTRAL_VOLUME), at_seconds=0.0),
    ]
    for deck in (1, 2):
        for band in ("low", "mid", "high"):
            steps.append(TimedAction(
                action=SetEQ(deck=deck, band=band, value=NEUTRAL_EQ),  # type: ignore[arg-type]
                at_seconds=0.0,
            ))
        steps.append(TimedAction(
            action=SetFilter(deck=deck, value=NEUTRAL_FILTER), at_seconds=0.0,
        ))
        steps.append(TimedAction(
            action=SetPitch(deck=deck, value=NEUTRAL_PITCH), at_seconds=0.0,
        ))
        for unit in (1, 2):
            steps.append(TimedAction(
                action=SetFx(deck=deck, unit=unit, value=NEUTRAL_FX),  # type: ignore[arg-type]
                at_seconds=0.0,
            ))
    return ActionPlan(steps=tuple(steps))


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
