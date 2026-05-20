"""
LLM-based parser. Calls Claude via the Claude Code CLI (`claude -p`) as a
subprocess and asks for JSON output, which we then validate against the
DJAction dataclasses.

Why CLI subprocess instead of the Anthropic SDK:
- Routes through the user's existing Claude Pro/Max subscription — no
  metered API key, no extra billing.
- One fewer Python dependency.
- A real-world AI-PM trade-off worth understanding: the CLI subprocess
  approach is ~500ms slower (process spawn overhead) and serializes
  through the user's local Claude Code install. For production, the
  Anthropic SDK gives you concurrency, lower latency, and reproducibility
  for users who don't have Claude Code installed.

This module's public interface (parse(text) -> DJAction) is identical
either way. Swapping to the SDK is a self-contained ~30-line change in
this file; nothing else in the codebase moves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from deckpilot.core.actions import (
    DJAction,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)
from .errors import ParseError


CLAUDE_BINARY = "claude"          # must be on PATH
TIMEOUT_SECONDS = 30


SYSTEM_PROMPT = """\
You are a parser for a DJ-control system called DeckPilot. Convert one
natural-language DJ command into a single JSON action.

Supported actions (output exactly one of these shapes):

  {"action": "play_deck",       "deck": 1 or 2}
  {"action": "pause_deck",      "deck": 1 or 2}
  {"action": "set_crossfader",  "value": float 0.0..1.0}
  {"action": "fade_to_deck",    "deck": 1 or 2, "seconds": float}
  {"action": "loop_deck",       "deck": 1 or 2, "beats": int (1,2,4,8,16,32)}
  {"action": "nudge_deck",      "deck": 1 or 2, "direction": "forward" or "back"}

If the command does not map to any of the above, return:
  {"action": "unknown", "reason": "<brief explanation>"}

Rules:
- Output ONLY the JSON. No prose, no markdown fences, no commentary.
- Deck numbers are 1 or 2 only. "deck A" = 1, "deck B" = 2.
- Crossfader value: 0.0 = full deck 1, 1.0 = full deck 2, 0.5 = center.
- Interpret intent generously: "kick into deck 2" = play_deck 2,
  "drop deck 1" = play_deck 1.
- If "fade" has no explicit duration, default to 8 seconds.
- If "loop" has no explicit beat count, default to 8.

Examples:
  "play deck 1"                       -> {"action":"play_deck","deck":1}
  "stop the second deck"              -> {"action":"pause_deck","deck":2}
  "fade to deck 2 over 4 seconds"     -> {"action":"fade_to_deck","deck":2,"seconds":4}
  "crossfader to the middle"          -> {"action":"set_crossfader","value":0.5}
  "loop deck 1 for sixteen beats"     -> {"action":"loop_deck","deck":1,"beats":16}
  "nudge the first deck forward"      -> {"action":"nudge_deck","deck":1,"direction":"forward"}
  "do a bass swap transition"         -> {"action":"unknown","reason":"multi-action sequences not yet supported"}
"""


class LLMParseError(ParseError):
    """Raised when the LLM returns invalid or unsupported JSON.

    Inherits from ParseError so callers (like __main__.py) can catch all
    parser failures with a single `except ParseError` clause.
    """


def parse(text: str) -> DJAction:
    """Call Claude via the `claude -p` CLI and turn its JSON into a DJAction."""
    if shutil.which(CLAUDE_BINARY) is None:
        raise LLMParseError(
            f"{CLAUDE_BINARY!r} CLI not found on PATH. "
            "Install Claude Code (https://claude.com/claude-code) or use the "
            "Anthropic SDK instead — see comments in deckpilot/core/parser/llm.py."
        )

    # We concatenate system + user prompt into one string. `claude -p` doesn't
    # have a dedicated --system flag the same way the SDK does, and inlining
    # the schema reminds the model to stay strict on the JSON shape.
    full_prompt = (
        SYSTEM_PROMPT
        + "\n\nUser command:\n"
        + text
        + "\n\nReturn ONLY the JSON object now. No preamble, no explanation."
    )

    try:
        result = subprocess.run(
            [CLAUDE_BINARY, "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMParseError(
            f"claude -p timed out after {TIMEOUT_SECONDS}s for input: {text!r}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise LLMParseError(
            f"claude -p exited with status {exc.returncode}. "
            f"stderr: {exc.stderr.strip()[:500]!r}"
        ) from exc

    raw = result.stdout.strip()
    payload = _extract_json(raw)
    return _payload_to_action(payload, original_text=text)


def _extract_json(raw: str) -> dict[str, Any]:
    """
    Pull the first JSON object out of the model's output.

    `claude -p` sometimes wraps output in markdown fences or prefixes it with
    a sentence even when told not to. We're forgiving: find the first '{' and
    the last '}' and try to parse what's between.
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMParseError(f"no JSON object found in LLM output: {raw!r}")

    candidate = raw[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMParseError(
            f"LLM output didn't contain valid JSON. raw={raw!r}, candidate={candidate!r}"
        ) from exc


def _payload_to_action(payload: dict[str, Any], *, original_text: str) -> DJAction:
    """Validate the LLM's JSON against our schema and instantiate a DJAction."""
    if not isinstance(payload, dict) or "action" not in payload:
        raise LLMParseError(f"LLM JSON missing 'action' field: {payload!r}")

    name = payload["action"]

    if name == "unknown":
        reason = payload.get("reason", "no reason given")
        raise LLMParseError(f"LLM declined: {reason} (input: {original_text!r})")

    try:
        if name == "play_deck":
            return PlayDeck(deck=int(payload["deck"]))
        if name == "pause_deck":
            return PauseDeck(deck=int(payload["deck"]))
        if name == "set_crossfader":
            return SetCrossfader(value=float(payload["value"]))
        if name == "fade_to_deck":
            return FadeToDeck(deck=int(payload["deck"]), seconds=float(payload["seconds"]))
        if name == "loop_deck":
            return LoopDeck(deck=int(payload["deck"]), beats=int(payload["beats"]))
        if name == "nudge_deck":
            direction = payload["direction"]
            if direction not in {"forward", "back"}:
                raise LLMParseError(f"invalid direction: {direction!r}")
            return NudgeDeck(deck=int(payload["deck"]), direction=direction)
    except (KeyError, ValueError, TypeError) as exc:
        raise LLMParseError(
            f"LLM JSON failed validation for action={name!r}: {payload!r}"
        ) from exc

    raise LLMParseError(f"unknown action name from LLM: {name!r}")
