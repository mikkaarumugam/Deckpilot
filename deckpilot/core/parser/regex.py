"""
Rule-based parser. Catches the most common command phrasings without needing
an LLM round-trip.

Each rule matches a single phrasing and produces a 1-step ActionPlan. For
multi-step commands (e.g. "bass swap"), the regex returns None and the
facade falls back to the LLM, which can plan multi-step sequences.

Adding a new rule:
    1. Write a regex. Use named groups.
    2. Append (pattern, factory) to RULES. Factory takes the match and
       returns a DJAction; the parser wraps it in an ActionPlan automatically.
    3. Add a test case in tests/test_parser.py.
"""

from __future__ import annotations

import re
from typing import Callable

from deckpilot.core.actions import (
    ActionPlan,
    DJAction,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    Sync,
)


def _band(name: str) -> str:
    """Normalize 'bass'/'low(s)' → 'low', 'mid(s)' → 'mid', 'high(s)'/'treble' → 'high'."""
    name = name.lower()
    if name == "bass" or name.startswith("low"):
        return "low"
    if name.startswith("mid"):
        return "mid"
    if name.startswith("high") or name == "treble":
        return "high"
    raise ValueError(f"unknown EQ band: {name!r}")


RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], DJAction]]] = [

    # "play deck 1" / "start deck 2"
    (
        re.compile(r"^(?:play|start)\s+deck\s+(?P<deck>[12])\s*$"),
        lambda m: PlayDeck(deck=int(m["deck"])),
    ),

    # "pause deck 1" / "stop deck 2"
    (
        re.compile(r"^(?:pause|stop)\s+deck\s+(?P<deck>[12])\s*$"),
        lambda m: PauseDeck(deck=int(m["deck"])),
    ),

    # "fade to deck 2 over 8 seconds"
    (
        re.compile(
            r"^fade\s+to\s+deck\s+(?P<deck>[12])"
            r"\s+over\s+(?P<seconds>\d+(?:\.\d+)?)\s+second(?:s)?\s*$"
        ),
        lambda m: FadeToDeck(deck=int(m["deck"]), seconds=float(m["seconds"])),
    ),

    # "loop deck 1 for 8 beats"
    (
        re.compile(
            r"^loop\s+deck\s+(?P<deck>[12])\s+for\s+(?P<beats>\d+)\s+beat(?:s)?\s*$"
        ),
        lambda m: LoopDeck(deck=int(m["deck"]), beats=int(m["beats"])),
    ),

    # "crossfader to the middle"
    (
        re.compile(r"^crossfader\s+(?:to\s+)?(?:the\s+)?(?:middle|center)\s*$"),
        lambda m: SetCrossfader(value=0.5),
    ),

    # "nudge deck 1 forward"
    (
        re.compile(
            r"^nudge\s+deck\s+(?P<deck>[12])"
            r"\s+(?P<direction>forward|back|backward)\s*$"
        ),
        lambda m: NudgeDeck(
            deck=int(m["deck"]),
            direction="back" if m["direction"] in {"back", "backward"} else "forward",
        ),
    ),

    # --- atomic shortcuts added in latency-opt pass ---
    # These move the most common single-action phrasings off the LLM path
    # (~1s → <1ms). Multi-step intents like "bass swap" still go to the LLM.

    # bare "play" / "start" → deck 1 default
    (
        re.compile(r"^(?:play|start)\s*$"),
        lambda m: PlayDeck(deck=1),
    ),

    # bare "pause" / "stop" → deck 1 default
    (
        re.compile(r"^(?:pause|stop)\s*$"),
        lambda m: PauseDeck(deck=1),
    ),

    # "kill the bass" / "cut the mids on deck 2" / "drop the highs"
    (
        re.compile(
            r"^(?:kill|cut|drop|mute)\s+(?:the\s+)?"
            r"(?P<band>bass|lows?|mids?|highs?|treble)"
            r"(?:\s+on\s+deck\s+(?P<deck>[12]))?\s*$"
        ),
        lambda m: SetEQ(
            deck=int(m["deck"] or 1),
            band=_band(m["band"]),  # type: ignore[arg-type]
            value=0.0,
        ),
    ),

    # "bring back the bass" / "restore the highs on deck 2" / "turn on bass"
    (
        re.compile(
            r"^(?:bring\s+back|restore|turn\s+on|return)\s+(?:the\s+)?"
            r"(?P<band>bass|lows?|mids?|highs?|treble)"
            r"(?:\s+on\s+deck\s+(?P<deck>[12]))?\s*$"
        ),
        lambda m: SetEQ(
            deck=int(m["deck"] or 1),
            band=_band(m["band"]),  # type: ignore[arg-type]
            value=1.0,
        ),
    ),

    # "sync deck 1" / "sync deck 2"
    (
        re.compile(r"^sync\s+deck\s+(?P<deck>[12])\s*$"),
        lambda m: Sync(deck=int(m["deck"])),
    ),

    # "stop loop" / "kill loop" / "exit loop" / "turn off loop" (deck 1 default)
    (
        re.compile(
            r"^(?:stop|kill|exit|end|turn\s+off)\s+(?:the\s+)?loop"
            r"(?:\s+on\s+deck\s+(?P<deck>[12]))?\s*$"
        ),
        lambda m: LoopDeck(deck=int(m["deck"] or 1), beats=8),
    ),
]


def parse(text: str) -> ActionPlan | None:
    """Return a 1-step ActionPlan if a rule matches, else None."""
    normalized = text.strip().lower()
    for pattern, factory in RULES:
        match = pattern.match(normalized)
        if match is not None:
            return ActionPlan.single(factory(match))
    return None
