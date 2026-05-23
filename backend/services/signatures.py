"""Render a DJAction to display-friendly strings for the React UI.

The frontend's PlanStep + CommandCard expect four labels per action:

  fn      — the signature shown in mono, e.g. "eq.low(deck:1)"
  detail  — human description shown below, e.g. "ramp 0.0 dB → −∞"
  t       — duration label, e.g. "4.0s" or "—"
  dMs     — execution-window milliseconds (used to drive the progress bar)

These mirror what the design's hardcoded examples (`design/pilot.jsx` lines
76-118) used, so the visual language stays consistent between the design
canvas and the real wired-up app.

Adding a new action type? Add a case below. Keep `fn` terse (this is
what shows in the chip) and `detail` informative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deckpilot.core.actions import (
    FadeToDeck,
    HotCue,
    LoadTrack,
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
)

if TYPE_CHECKING:
    from deckpilot.core.actions import DJAction


def render_action(action: DJAction) -> tuple[str, str, str, int]:
    """Return (fn, detail, t, dMs) for one atomic action.

    `dMs` defaults to 200 (single MIDI message round-trip) unless the
    action has a meaningful execution window (FadeToDeck, NudgeDeck).
    The frontend uses dMs only for the per-step progress bar — actual
    completion is signalled by the next step starting or by /state polling.
    """
    if isinstance(action, PlayDeck):
        return (
            f"transport.play(deck:{action.deck})",
            "set play=1",
            "—",
            200,
        )
    if isinstance(action, PauseDeck):
        return (
            f"transport.pause(deck:{action.deck})",
            "set play=0",
            "—",
            200,
        )
    if isinstance(action, SetCrossfader):
        return (
            "crossfade",
            f"set value={action.value:.2f}",
            "—",
            200,
        )
    if isinstance(action, FadeToDeck):
        return (
            f"fade.crossfader(deck:{action.deck})",
            f"ramp {action.seconds:.1f}s to deck {action.deck}",
            f"{action.seconds:.1f}s",
            int(action.seconds * 1000),
        )
    if isinstance(action, LoopDeck):
        return (
            f"loop.toggle(deck:{action.deck})",
            f"toggle {action.beats}-beat loop",
            "—",
            200,
        )
    if isinstance(action, NudgeDeck):
        return (
            f"nudge.{action.direction}(deck:{action.deck})",
            "100ms hold",
            "100ms",
            100,
        )
    if isinstance(action, SetEQ):
        # The design uses minus-infinity for full-cut and 0 dB for neutral.
        # Match that vocabulary in the detail string so the UI reads cleanly.
        if action.value <= 0.001:
            detail = "set  0.0 dB  →  −∞"
        elif action.value >= 0.999:
            detail = "restore  →  0.0 dB"
        else:
            detail = f"set value={action.value:.2f}"
        return (
            f"eq.{action.band}(deck:{action.deck})",
            detail,
            "—",
            200,
        )
    if isinstance(action, SetVolume):
        return (
            f"volume(deck:{action.deck})",
            f"set value={action.value:.2f}",
            "—",
            200,
        )
    if isinstance(action, HotCue):
        return (
            f"hotcue(deck:{action.deck}, cue:{action.cue})",
            f"jump to cue {action.cue}",
            "—",
            200,
        )
    if isinstance(action, Sync):
        return (
            f"tempo.sync(deck:{action.deck})",
            "match BPM + beat alignment",
            "—",
            200,
        )
    if isinstance(action, SetFilter):
        # Single-knob filter: 0.5 is bypass. Read the value in plain English
        # so the plan-step detail tells the user what they're about to hear.
        if action.value <= 0.001:
            detail = "full low-pass"
        elif action.value >= 0.999:
            detail = "full high-pass"
        elif abs(action.value - 0.5) <= 0.01:
            detail = "bypass"
        elif action.value < 0.5:
            detail = f"low-pass {(0.5 - action.value) * 2:.0%}"
        else:
            detail = f"high-pass {(action.value - 0.5) * 2:.0%}"
        return (
            f"filter(deck:{action.deck})",
            detail,
            "—",
            200,
        )
    if isinstance(action, SetFx):
        detail = "off" if action.value <= 0.001 else f"wet {action.value:.0%}"
        return (
            f"fx{action.unit}(deck:{action.deck})",
            detail,
            "—",
            200,
        )
    if isinstance(action, SetPitch):
        # Render as a ±% relative to Mixxx's default 8% range so the UI
        # shows musically-meaningful numbers instead of raw -1..+1 floats.
        if abs(action.value) <= 0.001:
            detail = "0 %"
        else:
            detail = f"{action.value * 8:+.1f} %"
        return (
            f"pitch(deck:{action.deck})",
            detail,
            "—",
            200,
        )
    if isinstance(action, LoadTrack):
        return (
            f"library.load(deck:{action.deck}, id:{action.track_id})",
            action.reasoning or "AI track suggestion",
            "—",
            0,  # not executed directly — surfaced as a suggestion
        )

    # Defensive: an unknown action type should never reach here, but
    # don't crash the response — render a placeholder.
    return (type(action).__name__, "(unrendered)", "—", 200)


def summary_signature(plan_actions: list) -> str:
    """Single-line signature for the whole plan. Goes in the parsed chip.

    For 1-step plans: just the action's signature.
    For multi-step: heuristic detection of known patterns (bass swap),
    otherwise a "multi-step(N)" label.
    """
    if not plan_actions:
        return "noop"
    if len(plan_actions) == 1:
        fn, _, _, _ = render_action(plan_actions[0])
        return fn

    # Heuristic: bass-swap is the canonical 6-step pattern we ship today.
    # Detect by shape: contains Sync + at least 2 SetEQ(band="low") + a
    # PlayDeck + a FadeToDeck.
    kinds = {type(a).__name__ for a in plan_actions}
    if {"Sync", "SetEQ", "PlayDeck", "FadeToDeck"}.issubset(kinds):
        decks = {a.deck for a in plan_actions if hasattr(a, "deck")}
        fade = next((a for a in plan_actions if isinstance(a, FadeToDeck)), None)
        deck_str = " → ".join(f"deck:{d}" for d in sorted(decks)) if len(decks) > 1 else f"deck:{next(iter(decks))}"
        t_str = f", t:{fade.seconds:.0f}s" if fade else ""
        return f"swap.bass({deck_str}{t_str})"

    return f"multi-step({len(plan_actions)})"


def affects_label(plan_actions: list) -> str:
    """Comma-list of the decks this plan touches. Goes in the "affects" UI hint."""
    decks = sorted({a.deck for a in plan_actions if hasattr(a, "deck")})
    if not decks:
        return "master"
    if len(decks) == 1:
        return f"deck {decks[0]}"
    return " · ".join(f"deck {d}" for d in decks)
