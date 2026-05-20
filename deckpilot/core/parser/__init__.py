"""
Parser facade — turns natural-language text into an ActionPlan.

Strategy: try the regex parser first (instant, free, deterministic). If it
returns None, fall back to the LLM parser (slower, can produce multi-step
plans, handles paraphrases).

This two-tier approach is a deliberate product decision. The 4-5 most
common phrasings cover ~70% of likely usage and don't need an LLM. The
LLM is reserved for "kick into the second drop in 4 bars" — phrasings
the regex would never hand-write a rule for AND for genuinely multi-step
moves like "bass swap into deck 2" that decompose into a coordinated
sequence of atomic actions.
"""

from __future__ import annotations

from deckpilot.core.actions import ActionPlan

from . import llm, regex
from .errors import ParseError  # re-exported for callers


def parse(text: str, *, mode: str = "auto") -> ActionPlan:
    """
    Parse natural-language text into an ActionPlan.

    mode:
        "auto"  — regex first, fall back to LLM (default)
        "regex" — regex only; raises ParseError on no match
        "llm"   — skip regex; go straight to the LLM
    """
    if mode not in {"auto", "regex", "llm"}:
        raise ValueError(f"unknown parser mode: {mode!r}")

    if mode in {"auto", "regex"}:
        result = regex.parse(text)
        if result is not None:
            return result
        if mode == "regex":
            raise ParseError(f"no regex rule matched: {text!r}")

    return llm.parse(text)
