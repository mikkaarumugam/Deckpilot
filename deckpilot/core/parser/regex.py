"""
Rule-based parser. Catches the most common command phrasings without needing
an LLM round-trip.

Coverage is intentionally narrow — we only match phrasings that are
unambiguous and high-frequency. Everything else returns None and the facade
falls back to the LLM.

Adding a new rule:
    1. Write a regex. Use named groups for clarity.
    2. Append (compiled_pattern, factory) to RULES.
    3. Add a test case in tests/test_parser.py.

Keep these LOWERCASE — the facade lowercases text before matching.
"""

from __future__ import annotations

import re
from typing import Callable

from deckpilot.core.actions import (
    DJAction,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)


# Each rule = (pattern, factory). factory takes the match and returns a DJAction.
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

    # "crossfader to the middle" / "crossfader middle"
    (
        re.compile(r"^crossfader\s+(?:to\s+)?(?:the\s+)?(?:middle|center)\s*$"),
        lambda m: SetCrossfader(value=0.5),
    ),

    # "nudge deck 1 forward" / "nudge deck 2 back"
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
]


def parse(text: str) -> DJAction | None:
    """Return a DJAction if any rule matches, otherwise None."""
    normalized = text.strip().lower()
    for pattern, factory in RULES:
        match = pattern.match(normalized)
        if match is not None:
            return factory(match)
    return None
