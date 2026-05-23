"""
Unit tests for the regex parser. Deterministic, no API key needed.

The LLM parser is exercised separately in tests/eval.py (M4) — that's an
"accuracy & latency report," not a unit test. LLM responses are noisy and
shouldn't be in the pytest gate.

Each regex match now produces a 1-step ActionPlan, so we assert on
`plan.steps[0].action` rather than the raw DJAction.
"""

from __future__ import annotations

import pytest

from deckpilot.core.actions import (
    ActionPlan,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetFilter,
    SetFx,
    SetPitch,
    Sync,
)
from deckpilot.core.parser import ParseError, regex, parse


# --- Regex parser hits ---

@pytest.mark.parametrize("text, expected_action", [
    # play
    ("play deck 1", PlayDeck(deck=1)),
    ("play deck 2", PlayDeck(deck=2)),
    ("start deck 1", PlayDeck(deck=1)),
    ("  PLAY  DECK  2  ", PlayDeck(deck=2)),

    # pause
    ("pause deck 1", PauseDeck(deck=1)),
    ("stop deck 2", PauseDeck(deck=2)),

    # fade
    ("fade to deck 2 over 8 seconds", FadeToDeck(deck=2, seconds=8.0)),
    ("fade to deck 1 over 10 seconds", FadeToDeck(deck=1, seconds=10.0)),
    ("fade to deck 2 over 4.5 seconds", FadeToDeck(deck=2, seconds=4.5)),
    ("fade to deck 2 over 1 second", FadeToDeck(deck=2, seconds=1.0)),

    # loop
    ("loop deck 1 for 8 beats", LoopDeck(deck=1, beats=8)),
    ("loop deck 2 for 16 beats", LoopDeck(deck=2, beats=16)),

    # crossfader
    ("crossfader to the middle", SetCrossfader(value=0.5)),
    ("crossfader middle", SetCrossfader(value=0.5)),
    ("crossfader to center", SetCrossfader(value=0.5)),

    # nudge
    ("nudge deck 1 forward", NudgeDeck(deck=1, direction="forward")),
    ("nudge deck 2 back", NudgeDeck(deck=2, direction="back")),
    ("nudge deck 1 backward", NudgeDeck(deck=1, direction="back")),

    # bare play/pause default to deck 1
    ("play", PlayDeck(deck=1)),
    ("start", PlayDeck(deck=1)),
    ("pause", PauseDeck(deck=1)),
    ("stop", PauseDeck(deck=1)),

    # kill / cut / drop EQ
    ("kill the bass", SetEQ(deck=1, band="low", value=0.0)),
    ("cut the bass", SetEQ(deck=1, band="low", value=0.0)),
    ("kill the bass on deck 2", SetEQ(deck=2, band="low", value=0.0)),
    ("kill the mids", SetEQ(deck=1, band="mid", value=0.0)),
    ("drop the highs on deck 2", SetEQ(deck=2, band="high", value=0.0)),
    ("mute the lows", SetEQ(deck=1, band="low", value=0.0)),

    # bring back / restore / turn on EQ
    ("bring back the bass", SetEQ(deck=1, band="low", value=1.0)),
    ("restore the bass on deck 2", SetEQ(deck=2, band="low", value=1.0)),
    ("turn on bass", SetEQ(deck=1, band="low", value=1.0)),
    ("return the highs on deck 1", SetEQ(deck=1, band="high", value=1.0)),

    # sync
    ("sync deck 1", Sync(deck=1)),
    ("sync deck 2", Sync(deck=2)),

    # loop off variants
    ("stop loop", LoopDeck(deck=1, beats=8)),
    ("kill loop", LoopDeck(deck=1, beats=8)),
    ("turn off the loop", LoopDeck(deck=1, beats=8)),
    ("exit loop on deck 2", LoopDeck(deck=2, beats=8)),

    # variable-beat loops (D-022): the existing regex already accepts any int;
    # only the adapter cares whether the size is bindable.
    ("loop deck 1 for 4 beats", LoopDeck(deck=1, beats=4)),
    ("loop deck 2 for 32 beats", LoopDeck(deck=2, beats=32)),

    # filter (D-022) — single knob, 0.0 LPF / 0.5 bypass / 1.0 HPF
    ("low pass deck 1", SetFilter(deck=1, value=0.0)),
    ("low-pass on deck 2", SetFilter(deck=2, value=0.0)),
    ("lowpass", SetFilter(deck=1, value=0.0)),
    ("high pass deck 2", SetFilter(deck=2, value=1.0)),
    ("highpass", SetFilter(deck=1, value=1.0)),
    ("filter off", SetFilter(deck=1, value=0.5)),
    ("filter off on deck 2", SetFilter(deck=2, value=0.5)),
    ("no filter", SetFilter(deck=1, value=0.5)),
    ("reset filter on deck 2", SetFilter(deck=2, value=0.5)),

    # FX wet (D-022)
    ("fx 1 to 50% on deck 1", SetFx(deck=1, unit=1, value=0.5)),
    ("fx2 80% on deck 2", SetFx(deck=2, unit=2, value=0.8)),
    ("effect 1 to 100% on deck 1", SetFx(deck=1, unit=1, value=1.0)),
    ("kill fx 1 on deck 2", SetFx(deck=2, unit=1, value=0.0)),
    ("no fx 2", SetFx(deck=1, unit=2, value=0.0)),

    # pitch (D-022) — bare ±, then percent → fractional of ±8% range
    ("pitch deck 1 up", SetPitch(deck=1, value=1.0)),
    ("pitch deck 2 down", SetPitch(deck=2, value=-1.0)),
    ("pitch deck 1 up 4%", SetPitch(deck=1, value=0.5)),
    ("pitch deck 2 down 8%", SetPitch(deck=2, value=-1.0)),
    ("pitch up", SetPitch(deck=1, value=1.0)),
    ("reset pitch", SetPitch(deck=1, value=0.0)),
    ("reset pitch on deck 2", SetPitch(deck=2, value=0.0)),
])
def test_regex_parse_matches(text: str, expected_action) -> None:
    """Each canonical phrasing produces a 1-step plan with the expected action at t=0."""
    plan = regex.parse(text)
    assert plan is not None
    assert isinstance(plan, ActionPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].at_seconds == 0.0
    assert plan.steps[0].action == expected_action


# --- Regex parser misses ---

@pytest.mark.parametrize("text", [
    "",
    "do a bass swap",                      # multi-step — LLM territory
    "kick into the second drop",
    "fade to deck 3 over 8 seconds",       # invalid deck
    "play deck",
    "fade to deck 1",
])
def test_regex_parse_misses(text: str) -> None:
    assert regex.parse(text) is None


# --- Facade behavior ---

def test_facade_regex_mode_raises_on_miss() -> None:
    with pytest.raises(ParseError):
        parse("do a bass swap", mode="regex")


def test_facade_regex_mode_returns_plan_on_hit() -> None:
    plan = parse("play deck 1", mode="regex")
    assert isinstance(plan, ActionPlan)
    assert plan.steps[0].action == PlayDeck(deck=1)


def test_facade_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        parse("play deck 1", mode="nonsense")
