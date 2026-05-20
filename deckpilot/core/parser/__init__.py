"""
Parser facade.

Strategy: try the regex parser first (instant, free, deterministic). If it
returns None, fall back to the LLM parser (slower, costs API tokens, but
handles paraphrases).

This two-tier approach is a deliberate product decision. The 4-5 most
common phrasings cover ~70% of likely usage and don't need an LLM. The
LLM is reserved for "kick into the second drop in 4 bars" — phrasings
the regex would never hand-write a rule for.

Why this matters for an AI PM portfolio:
- Latency: regex matches in microseconds; the LLM takes 1-3 seconds.
- Cost: regex is free; the LLM is ~$0.001 per call at Haiku pricing.
- Reliability: regex is deterministic and unit-testable; the LLM can fail
  in surprising ways and needs an eval suite (see tests/eval.py in M4).
"""

from __future__ import annotations

from deckpilot.core.actions import DJAction

from . import llm, regex
from .errors import ParseError  # re-exported for callers


def parse(text: str, *, mode: str = "auto") -> DJAction:
    """
    Parse natural-language text into a DJAction.

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

    # Fall through to LLM (mode == "auto" with no regex match, or mode == "llm").
    return llm.parse(text)
