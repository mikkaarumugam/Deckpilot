"""
Tiny regex parser for the most common commands. Catches the easy cases so we
don't pay an LLM round-trip for "play deck 1".

Covers (planned):
    play deck N
    pause deck N
    fade to deck N over M seconds

Anything else returns None and the facade falls back to the LLM parser.
"""

from __future__ import annotations

# TODO(M3): implement parse(text) -> DJAction | None
