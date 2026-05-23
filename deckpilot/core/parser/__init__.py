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

from typing import TYPE_CHECKING

from deckpilot.core.actions import ActionPlan
from deckpilot.core.agent import AgentSchedule

from . import llm, regex
from .errors import ParseError  # re-exported for callers

if TYPE_CHECKING:
    from deckpilot.adapters.midi_feedback import MixxxState
    from deckpilot.library import LibraryReader


def parse(
    text: str,
    *,
    mode: str = "auto",
    library: "LibraryReader | None" = None,
    deck_state: "MixxxState | None" = None,
) -> "ActionPlan | AgentSchedule":
    """
    Parse natural-language text into either an ActionPlan (single-shot)
    or an AgentSchedule (autonomous goal with triggers; D-021).

    mode:
        "auto"  — regex first, fall back to LLM (default)
        "regex" — regex only; raises ParseError on no match (regex never
                  produces schedules — only the LLM can)
        "llm"   — skip regex; go straight to the LLM

    `library` and `deck_state` are runtime context forwarded to the LLM
    when it's invoked (regex doesn't need them). Without them, library-
    aware actions like LoadTrack will be declined.

    Callers check `isinstance(result, AgentSchedule)` to route schedules
    to the agent runtime; ActionPlan responses go through the normal
    /execute path.
    """
    if mode not in {"auto", "regex", "llm"}:
        raise ValueError(f"unknown parser mode: {mode!r}")

    if mode in {"auto", "regex"}:
        result = regex.parse(text)
        if result is not None:
            return result
        if mode == "regex":
            raise ParseError(f"no regex rule matched: {text!r}")

    return llm.parse(text, library=library, deck_state=deck_state)
