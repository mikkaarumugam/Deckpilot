"""
Unit tests for the regex parser. Deterministic, no API key needed.

The LLM parser is exercised separately in tests/eval.py (M4) — that's an
"accuracy & latency report," not a unit test. LLM responses are noisy and
shouldn't be in the pytest gate.
"""

from __future__ import annotations

import pytest

from deckpilot.core.actions import (
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)
from deckpilot.core.parser import ParseError, regex, parse


# --- Regex parser hits ---

@pytest.mark.parametrize("text, expected", [
    # play
    ("play deck 1", PlayDeck(deck=1)),
    ("play deck 2", PlayDeck(deck=2)),
    ("start deck 1", PlayDeck(deck=1)),
    ("  PLAY  DECK  2  ", PlayDeck(deck=2)),   # case + whitespace tolerance

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
])
def test_regex_parse_matches(text: str, expected) -> None:
    """Each canonical phrasing produces the expected DJAction."""
    assert regex.parse(text) == expected


# --- Regex parser misses ---

@pytest.mark.parametrize("text", [
    "",                                    # empty
    "do a bass swap",                      # not a recognized verb
    "kick into the second drop",           # paraphrase — LLM territory
    "fade to deck 3 over 8 seconds",       # invalid deck
    "play deck",                           # missing deck number
    "fade to deck 1",                      # missing duration
])
def test_regex_parse_misses(text: str) -> None:
    """Anything outside the rule set returns None so the facade can fall back."""
    assert regex.parse(text) is None


# --- Facade behavior ---

def test_facade_regex_mode_raises_on_miss() -> None:
    """mode='regex' surfaces a ParseError instead of falling through to the LLM."""
    with pytest.raises(ParseError):
        parse("do a bass swap", mode="regex")


def test_facade_regex_mode_returns_on_hit() -> None:
    """Regex-only mode still returns matches normally."""
    assert parse("play deck 1", mode="regex") == PlayDeck(deck=1)


def test_facade_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        parse("play deck 1", mode="nonsense")
