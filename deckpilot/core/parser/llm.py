"""
LLM-based parser. Calls Claude via the Claude Code CLI (`claude -p`) as a
subprocess and asks for an ActionPlan (one or more timed actions) as JSON.
The plan is validated against our schema before returning.

Why CLI subprocess instead of the Anthropic SDK:
- Routes through the user's existing Claude Pro/Max subscription — no
  metered API key, no extra billing.
- Real-world AI-PM trade-off: ~500ms slower (process spawn), serializes
  through the local Claude Code install. For production, the SDK gives
  you concurrency, lower latency, and reproducibility for users without
  Claude Code installed. Swap is self-contained ~30 lines in this file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from deckpilot.core.actions import (
    ActionPlan,
    DJAction,
    FadeToDeck,
    HotCue,
    LoadTrack,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetVolume,
    Sync,
    TimedAction,
)
from .errors import ParseError

if TYPE_CHECKING:
    from deckpilot.adapters.midi_feedback import MixxxState
    from deckpilot.library import LibraryReader


CLAUDE_BINARY = "claude"
TIMEOUT_SECONDS = 30

# Pin to Haiku. Parsing is a classification task with constrained JSON output;
# the system prompt does the heavy lifting via schema + examples, so a small
# fast model is correct. Sonnet/Opus would be wasted spend + latency.
# If accuracy drops on edge cases (track via tests/eval.py), the right move is
# to route fancier cases to Sonnet, not to upgrade the default.
LLM_MODEL = "haiku"


SYSTEM_PROMPT_BASE = """\
You are a parser for a DJ-control system called DeckPilot. Convert a
natural-language DJ command into an ActionPlan: a JSON object describing
one or more timed actions.

Output format (ALWAYS this exact shape):
{
  "plan": [
    {"at": <seconds-from-plan-start>, "action": "<action_name>", ...action params}
  ]
}

For an UNKNOWN/unsupported command:
{ "plan": [], "unknown": "<brief reason>" }

Supported atomic actions:
  play_deck      {"action":"play_deck",      "deck":1|2}
  pause_deck     {"action":"pause_deck",     "deck":1|2}
  set_crossfader {"action":"set_crossfader", "value":float 0..1}
  fade_to_deck   {"action":"fade_to_deck",   "deck":1|2, "seconds":float}
  loop_deck      {"action":"loop_deck",      "deck":1|2, "beats":int}
  nudge_deck     {"action":"nudge_deck",     "deck":1|2, "direction":"forward"|"back"}
  set_eq         {"action":"set_eq",         "deck":1|2, "band":"low"|"mid"|"high", "value":float 0..1}
  set_volume     {"action":"set_volume",     "deck":1|2, "value":float 0..1}
  hot_cue        {"action":"hot_cue",        "deck":1|2, "cue":int 1..8}
  sync           {"action":"sync",           "deck":1|2}
  load_track     {"action":"load_track",     "deck":1|2, "track_id":int, "reasoning":string}    // only when LIBRARY CONTEXT is provided. "reasoning" is one short line explaining the pick (BPM fit, key, vibe).

Rules:
- Output ONLY JSON. No prose, no markdown fences.
- "at" is absolute seconds from plan start, e.g. 0, 2, 4.5.
- Deck is 1 or 2. "deck A" = 1, "deck B" = 2.
- **If the user doesn't specify a deck, DEFAULT TO DECK 1.** Never refuse
  on "deck not specified" — pick deck 1 and emit the action.
- Crossfader: 0.0 = full deck 1, 1.0 = full deck 2, 0.5 = center.
- EQ value: 0.0 = full cut (kill that band), 1.0 = neutral (restored).
- Vocabulary mapping for EQ:
    "kill" / "cut" / "drop" / "remove" / "turn off" + bass/mid/highs → set_eq value=0.0
    "bring back" / "restore" / "turn on" / "return" + bass/mid/highs → set_eq value=1.0
- Loops are TOGGLES — calling loop_deck again turns an active loop off.
    "loop deck 1 for 8 beats" → loop_deck (turns on)
    "stop loop" / "kill loop" / "turn off loop" / "exit loop" → loop_deck again (turns off)
- Interpret intent generously: "drop deck 2" = play_deck 2, "kick into the second deck" = play_deck 2.
- Default fade duration: 8s. Default loop: 8 beats.
- ONLY return "unknown" for things genuinely outside the action vocabulary
  (track selection, library navigation, recording, broadcast, effects).
  Don't decline for missing parameters — fill in sensible defaults.

SIMPLE examples (note how missing deck defaults to 1, never refused):
"play deck 1"          -> {"plan":[{"at":0,"action":"play_deck","deck":1}]}
"play"                 -> {"plan":[{"at":0,"action":"play_deck","deck":1}]}
"turn bass on"         -> {"plan":[{"at":0,"action":"set_eq","deck":1,"band":"low","value":1.0}]}
"bring back the bass"  -> {"plan":[{"at":0,"action":"set_eq","deck":1,"band":"low","value":1.0}]}
"kill the highs"       -> {"plan":[{"at":0,"action":"set_eq","deck":1,"band":"high","value":0.0}]}
"stop loop"            -> {"plan":[{"at":0,"action":"loop_deck","deck":1,"beats":8}]}
"kill loop"            -> {"plan":[{"at":0,"action":"loop_deck","deck":1,"beats":8}]}
"turn off the loop"    -> {"plan":[{"at":0,"action":"loop_deck","deck":1,"beats":8}]}

MULTI-STEP example: bass swap (the canonical EQ-based DJ transition):
"bass swap into deck 2" ->
{
  "plan": [
    {"at":0, "action":"sync",           "deck":2},
    {"at":0, "action":"set_eq",         "deck":2, "band":"low", "value":0.0},
    {"at":0, "action":"play_deck",      "deck":2},
    {"at":0, "action":"fade_to_deck",   "deck":2, "seconds":4},
    {"at":2, "action":"set_eq",         "deck":1, "band":"low", "value":0.0},
    {"at":4, "action":"set_eq",         "deck":2, "band":"low", "value":1.0}
  ]
}

Bass-swap rationale (so you can adapt for variants like "8-second bass swap"):
- Pre-cut deck 2's bass and sync it BEFORE starting (no audible double-bass).
- Start deck 2 and begin the crossfader fade.
- At the fade midpoint, cut deck 1's bass (clean handoff).
- At the fade end, bring deck 2's bass back to neutral.
- Always: bass-cut events go to set_eq with band="low", value=0.0.

LIBRARY-AWARE example (only valid when LIBRARY CONTEXT is provided):
"queue a daft punk track on deck 2" ->
{"plan":[{"at":0,"action":"load_track","deck":2,"track_id":<id>,"reasoning":"<one short line>"}]}

Reasoning style — keep it tight, 1-2 short clauses naming the picked criteria.
Examples of good reasoning strings:
  "121.3 BPM fits deck 1's 116 with a small pitch nudge; key C is neutral"
  "90.6 BPM matches the user's '~90' ask exactly"
  "Lowest-BPM track in the library — best fit for 'chill'"
  "Only Daft Punk track at a BPM compatible with deck 1's 116"
Bad reasoning (skip these): "this is a good track", "user requested it",
empty string, more than two sentences.

LIBRARY-AWARE + multi-step ("queue X and bass swap into it" — pick the most
BPM-compatible track to the currently-playing deck, then transition):
"queue a daft punk track and bass swap into deck 2 over 4 seconds" ->
{
  "plan": [
    {"at":0, "action":"load_track",     "deck":2, "track_id":<id>, "reasoning":"<one line>"},
    {"at":0, "action":"sync",           "deck":2},
    {"at":0, "action":"set_eq",         "deck":2, "band":"low", "value":0.0},
    {"at":0, "action":"play_deck",      "deck":2},
    {"at":0, "action":"fade_to_deck",   "deck":2, "seconds":4},
    {"at":2, "action":"set_eq",         "deck":1, "band":"low", "value":0.0},
    {"at":4, "action":"set_eq",         "deck":2, "band":"low", "value":1.0}
  ]
}

Track-selection guidance (when LIBRARY CONTEXT is provided):
- Pick by criteria the user gave: artist, genre, BPM range, "vibe".
- Prefer tracks whose BPM is within ~6 BPM of the currently-playing deck
  (good for sync without huge pitch nudging). When the user is asking to
  transition, this is especially important.
- Prefer tracks whose key is musically compatible (same key, relative
  minor/major, or +/-1 in the Camelot wheel) — but BPM compatibility
  matters more than key.
- If the user says "queue/load/find X" without specifying a deck, pick the
  deck that ISN'T currently playing (from CURRENT DECK STATE below). If
  both are paused, default to deck 2.
- If MULTIPLE tracks match equally, pick the one with timesplayed=0 (a
  "rotate the catalog" heuristic). The library snapshot doesn't include
  timesplayed yet, so for now just pick the first ID in the list.
- If NO tracks match, decline cleanly: {"plan":[],"unknown":"no matching tracks in library"}.

UNKNOWN example (with NO library context provided):
"play me a Daft Punk song" -> {"plan":[], "unknown":"track selection not supported (no library context)"}
"""


def _render_library_block(library: "LibraryReader | None") -> str:
    """One compact snapshot block per parse call. The model uses these
    ids to emit load_track actions. Skipped entirely when no library
    is provided, which keeps the prompt small for non-library prompts."""
    if library is None:
        return ""
    tracks = library.list_tracks()
    if not tracks:
        return "\nLIBRARY CONTEXT: (empty library — decline any track-selection request)\n"
    lines = ["", "LIBRARY CONTEXT (all available tracks, reference by id):"]
    for t in tracks:
        bpm = f"{t.bpm:.1f}" if t.bpm > 0 else "?"
        key = t.key or "?"
        genre = t.genre or "?"
        # Compact one-liner so even a 200-track library fits in a few KB.
        lines.append(
            f"  id={t.id}: {t.artist} — {t.title}  "
            f"[bpm={bpm}, key={key}, genre={genre}]"
        )
    return "\n".join(lines) + "\n"


def _render_deck_state_block(deck_state: "MixxxState | None") -> str:
    """Live deck state from Mixxx feedback. Optional — when provided
    the model uses it for 'pick the deck that isn't playing' decisions."""
    if deck_state is None:
        return ""
    lines = ["", "CURRENT DECK STATE (from Mixxx live feedback):"]
    for n in (1, 2):
        d = deck_state.deck(n)
        bpm = f"{d.bpm:.1f}" if d.bpm > 0 else "?"
        status = "PLAYING" if d.playing else "paused"
        lines.append(f"  deck {n}: {status}, bpm={bpm}")
    return "\n".join(lines) + "\n"


def build_system_prompt(
    library: "LibraryReader | None" = None,
    deck_state: "MixxxState | None" = None,
) -> str:
    """Compose the full system prompt with optional runtime context."""
    return (
        SYSTEM_PROMPT_BASE
        + _render_library_block(library)
        + _render_deck_state_block(deck_state)
    )


# Static export for callers that don't have runtime context (tests, the
# regex eval) — backwards compatible with v0.1.
SYSTEM_PROMPT = build_system_prompt()


class LLMParseError(ParseError):
    """Raised when the LLM returns invalid or unsupported JSON."""


def parse(
    text: str,
    *,
    library: "LibraryReader | None" = None,
    deck_state: "MixxxState | None" = None,
) -> ActionPlan:
    """Call Claude via `claude -p` and turn its JSON into an ActionPlan.

    `library` and `deck_state` are optional runtime context. When
    provided, the LLM can pick tracks (LoadTrack) and reason about which
    deck to use. When omitted, the model declines library-related
    requests with a clear reason.
    """
    if shutil.which(CLAUDE_BINARY) is None:
        raise LLMParseError(
            f"{CLAUDE_BINARY!r} CLI not found on PATH. Install Claude Code "
            "(https://claude.com/claude-code) or swap to the Anthropic SDK — "
            "see the module docstring in deckpilot/core/parser/llm.py."
        )

    full_prompt = (
        build_system_prompt(library=library, deck_state=deck_state)
        + "\n\nUser command:\n"
        + text
        + "\n\nReturn ONLY the JSON object now."
    )

    try:
        result = subprocess.run(
            [CLAUDE_BINARY, "-p", "--model", LLM_MODEL, full_prompt],
            capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMParseError(f"claude -p timed out after {TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        raise LLMParseError(
            f"claude -p exited with status {exc.returncode}. "
            f"stderr: {exc.stderr.strip()[:500]!r}"
        ) from exc

    raw = result.stdout.strip()
    payload = _extract_json(raw)
    return _payload_to_plan(payload, original_text=text)


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of the model's output (tolerates extra prose)."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMParseError(f"no JSON object found in LLM output: {raw!r}")
    candidate = raw[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMParseError(
            f"LLM output not valid JSON. raw={raw!r}, candidate={candidate!r}"
        ) from exc


def _payload_to_plan(payload: dict[str, Any], *, original_text: str) -> ActionPlan:
    if not isinstance(payload, dict):
        raise LLMParseError(f"LLM JSON is not an object: {payload!r}")

    if "unknown" in payload or payload.get("plan") == []:
        reason = payload.get("unknown", "no reason given")
        raise LLMParseError(f"LLM declined: {reason} (input: {original_text!r})")

    if "plan" not in payload or not isinstance(payload["plan"], list):
        raise LLMParseError(f"LLM JSON missing 'plan' list: {payload!r}")

    steps: list[TimedAction] = []
    for i, raw_step in enumerate(payload["plan"]):
        if not isinstance(raw_step, dict):
            raise LLMParseError(f"plan step {i} is not an object: {raw_step!r}")
        at_seconds = float(raw_step.get("at", 0.0))
        action = _payload_to_action(raw_step, original_text=original_text)
        steps.append(TimedAction(action=action, at_seconds=at_seconds))

    if not steps:
        raise LLMParseError(f"LLM returned empty plan for: {original_text!r}")

    return ActionPlan(steps=tuple(steps))


def _payload_to_action(payload: dict[str, Any], *, original_text: str) -> DJAction:
    if "action" not in payload:
        raise LLMParseError(f"plan step missing 'action': {payload!r}")

    name = payload["action"]

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
        if name == "set_eq":
            band = payload["band"]
            if band not in {"low", "mid", "high"}:
                raise LLMParseError(f"invalid EQ band: {band!r}")
            return SetEQ(deck=int(payload["deck"]), band=band, value=float(payload["value"]))
        if name == "set_volume":
            return SetVolume(deck=int(payload["deck"]), value=float(payload["value"]))
        if name == "hot_cue":
            return HotCue(deck=int(payload["deck"]), cue=int(payload["cue"]))
        if name == "sync":
            return Sync(deck=int(payload["deck"]))
        if name == "load_track":
            return LoadTrack(
                deck=int(payload["deck"]),
                track_id=int(payload["track_id"]),
                reasoning=str(payload.get("reasoning", "")).strip(),
            )
    except (KeyError, ValueError, TypeError) as exc:
        raise LLMParseError(
            f"LLM JSON failed validation for action={name!r}: {payload!r}"
        ) from exc

    raise LLMParseError(f"unknown action name from LLM: {name!r}")
