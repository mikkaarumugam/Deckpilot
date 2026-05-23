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
    LOOP_BEAT_SIZES,
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
    SetFilter,
    SetFx,
    SetPitch,
    SetVolume,
    Sync,
    TimedAction,
)
from deckpilot.core.agent import (
    AgentSchedule,
    DeckPosition,
    Immediate,
    ScheduledPlan,
    Trigger,
)
from .errors import ParseError

if TYPE_CHECKING:
    from deckpilot.adapters.midi_feedback import MixxxState
    from deckpilot.library import LibraryReader


CLAUDE_BINARY = "claude"
# 60s ceiling. Was 30s but library-aware Q&A prompts ("what should I mix
# into X?") and long mini-set plans regularly need more — Haiku's extended-
# thinking pass alone can take ~10-20s on those. Demo paths are still
# fast; this just gives the slow paths room.
TIMEOUT_SECONDS = 60

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
  loop_deck      {"action":"loop_deck",      "deck":1|2, "beats":int in {1,2,4,8,16,32}}
  nudge_deck     {"action":"nudge_deck",     "deck":1|2, "direction":"forward"|"back"}
  set_eq         {"action":"set_eq",         "deck":1|2, "band":"low"|"mid"|"high", "value":float 0..1}
  set_volume     {"action":"set_volume",     "deck":1|2, "value":float 0..1}
  set_filter     {"action":"set_filter",     "deck":1|2, "value":float 0..1}  // 0.0=full LPF, 0.5=bypass, 1.0=full HPF (one knob)
  set_fx         {"action":"set_fx",         "deck":1|2, "unit":1|2, "value":float 0..1}  // wet level on FX unit; 0.0 disables routing
  set_pitch      {"action":"set_pitch",      "deck":1|2, "value":float -1..+1}  // -1=full down, 0=neutral, +1=full up (±8% range)
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
- Allowed loop sizes: {1, 2, 4, 8, 16, 32} beats. If the user asks for a
  non-power-of-2 size, round to the nearest allowed value.
- Filter knob: ONE knob per deck. 0.5 is bypass (no filter). "low pass" /
  "lowpass" / "LPF" → value 0.0. "high pass" / "HPF" → value 1.0.
  "sweep up the filter" → ramp from 0.5 toward 1.0. "filter off" → 0.5.
- FX wet: "fx 1 to 50% on deck 1" → set_fx deck=1 unit=1 value=0.5.
  "kill fx 1" / "no fx 2" → value 0.0 (disables routing on that deck).
  Trade-off: Mixxx's unit mix is global per unit, so two decks routed to
  the same unit share the wet level. Don't worry about this — just emit
  per-deck set_fx calls; the adapter handles it.
- Pitch: "pitch up" / "pitch down" → ±1.0 (full slider). "pitch up 4%" →
  +0.5 (half the ±8% range). "reset pitch" → 0.0.
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
"loop 4 beats"         -> {"plan":[{"at":0,"action":"loop_deck","deck":1,"beats":4}]}
"low pass deck 1"      -> {"plan":[{"at":0,"action":"set_filter","deck":1,"value":0.0}]}
"high pass deck 2"     -> {"plan":[{"at":0,"action":"set_filter","deck":2,"value":1.0}]}
"filter off"           -> {"plan":[{"at":0,"action":"set_filter","deck":1,"value":0.5}]}
"fx 1 to 50% deck 1"   -> {"plan":[{"at":0,"action":"set_fx","deck":1,"unit":1,"value":0.5}]}
"kill fx 2 on deck 2"  -> {"plan":[{"at":0,"action":"set_fx","deck":2,"unit":2,"value":0.0}]}
"pitch deck 1 up"      -> {"plan":[{"at":0,"action":"set_pitch","deck":1,"value":1.0}]}
"pitch deck 2 down 4%" -> {"plan":[{"at":0,"action":"set_pitch","deck":2,"value":-0.5}]}
"reset pitch"          -> {"plan":[{"at":0,"action":"set_pitch","deck":1,"value":0.0}]}

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

Questions about the library (when LIBRARY CONTEXT is provided):
- Treat questions like "what should I mix into X?" / "what works with Y?" /
  "suggest something for deck 2" as load-suggestions. Pick your top track,
  emit a SINGLE load_track step with the reasoning explaining WHY (BPM
  compatibility, key compatibility, vibe match). Do NOT generate a full
  plan — just the load_track. The dashboard will surface this as a
  suggestion card; the user decides whether to load it.
- If the user mentions a track that's not in the library (e.g. "what should
  I mix into Strobe by Deadmau5" but no Deadmau5 in your library), still
  reason about what the abstract track is like (your training knowledge),
  then pick the closest match from what IS in the library. Reasoning
  should explain the analogy.

UNKNOWN example (with NO library context provided):
"play me a Daft Punk song" -> {"plan":[], "unknown":"track selection not supported (no library context)"}

Goal-style prompts (autonomous schedules):
- When the user describes a TIMED SEQUENCE — anything with "then", "when X
  ends", "after", "later", "auto-transition", "in N seconds, do Y" — emit
  a SCHEDULE instead of a single plan. Schedules are how DeckPilot does
  autonomous behaviour without manual prompts in between.
- Schedule shape (alternative top-level response):
  {
    "schedule": [
      {
        "trigger": {"type": "immediate"},
        "label": "<one-line human description>",
        "plan": [<TimedActions, just like a normal plan>]
      },
      {
        "trigger": {"type": "deck_position", "deck": <1|2>, "at": 0.92},
        "label": "transition into <track>",
        "plan": [<TimedActions for the transition>]
      }
    ],
    "reasoning": "<one-line explanation of the energy/key/BPM logic>"
  }
- Trigger types currently supported:
    - {"type": "immediate"}     — fires the moment the schedule starts.
    - {"type": "deck_position", "deck": N, "at": 0.92} — fires when
      that deck's playhead is ≥ the fraction. Use at=0.92 for
      "near end"; at=0.5 for "midway"; etc.
- Each schedule step's `plan` follows the same TimedAction shape as
  normal plans — load_track, play_deck, set_eq, fade_to_deck, etc.
- Keep schedules SHORT (2-3 steps) for the demo: an immediate kickoff
  + one or two timed transitions. Multi-track 5+ step sequences are
  out of scope right now.
- If the user says "play X then auto-transition into Y when X ends",
  produce a 2-step schedule: immediate kickoff for X, deck_position
  trigger at 0.92 for the transition into Y.
- For NON-goal prompts (single commands, suggestions, questions), still
  emit a regular {"plan":[...]} — don't wrap simple commands in a
  schedule.

SCHEDULE example:
"play berlioz on deck 1 then auto-transition into highjack when berlioz is near end, bass swap over 8 seconds"
-> {
  "schedule": [
    {"trigger": {"type":"immediate"}, "label":"play berlioz",
     "plan": [{"at":0,"action":"load_track","deck":1,"track_id":7,"reasoning":"opener"},
              {"at":0,"action":"play_deck","deck":1}]},
    {"trigger": {"type":"deck_position","deck":1,"at":0.92}, "label":"bass swap into highjack",
     "plan": [{"at":0,"action":"load_track","deck":2,"track_id":10,"reasoning":"75 BPM half-time of 153/2"},
              {"at":0,"action":"set_eq","deck":2,"band":"low","value":0.0},
              {"at":0,"action":"play_deck","deck":2},
              {"at":0,"action":"fade_to_deck","deck":2,"seconds":8},
              {"at":4,"action":"set_eq","deck":1,"band":"low","value":0.0},
              {"at":8,"action":"set_eq","deck":2,"band":"low","value":1.0}]}
  ],
  "reasoning":"berlioz outro → highjack bass swap; 116/87 BPM gap covered by long fade"
}
"""


def _render_library_block(library: "LibraryReader | None") -> str:
    """One compact snapshot block per parse call. The model uses these
    ids to emit load_track actions. Skipped entirely when no library
    is provided, which keeps the prompt small for non-library prompts.

    `dur` (mm:ss) is included so the model can plan mini-sets that
    respect track length — e.g. "transition near the end" maps to a
    sensible at_seconds offset instead of a hallucinated guess.
    Adds ~6 chars/row to the prompt; negligible at <200 tracks.
    """
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
        dur = _format_duration(t.duration)
        # Compact one-liner so even a 200-track library fits in a few KB.
        lines.append(
            f"  id={t.id}: {t.artist} — {t.title}  "
            f"[bpm={bpm}, key={key}, genre={genre}, dur={dur}]"
        )
    return "\n".join(lines) + "\n"


def _format_duration(seconds: float) -> str:
    """Render a track length as m:ss (e.g. 3:42). Returns '?' for
    un-analysed tracks (duration==0) so the model can distinguish
    'unknown' from 'really short'."""
    if seconds <= 0:
        return "?"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


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
) -> "ActionPlan | AgentSchedule":
    """Call Claude via `claude -p` and turn its JSON into either an
    ActionPlan (single-shot) or an AgentSchedule (goal-style prompt
    with triggers; D-021).

    `library` and `deck_state` are optional runtime context. When
    provided, the LLM can pick tracks (LoadTrack) and reason about which
    deck to use. When omitted, the model declines library-related
    requests with a clear reason.

    Return type is a union — callers check isinstance and route
    accordingly. The shape is decided by the LLM based on the prompt
    (timed-sequence language triggers schedules; single commands
    produce plans).
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
    if payload_has_schedule(payload):
        return _payload_to_schedule(payload, original_text=text)
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


def payload_has_schedule(payload: dict[str, Any]) -> bool:
    """True when the LLM emitted a schedule-shaped response (goal-style
    prompt). Caller routes to _payload_to_schedule instead of
    _payload_to_plan."""
    return isinstance(payload, dict) and isinstance(payload.get("schedule"), list)


def _payload_to_trigger(payload: dict[str, Any]) -> Trigger:
    """Validate + convert one trigger dict from the LLM into a Trigger."""
    if not isinstance(payload, dict):
        raise LLMParseError(f"trigger is not an object: {payload!r}")
    kind = payload.get("type")
    if kind == "immediate":
        return Immediate()
    if kind == "deck_position":
        deck = payload.get("deck")
        at = payload.get("at")
        if deck not in (1, 2):
            raise LLMParseError(f"deck_position trigger: deck must be 1 or 2, got {deck!r}")
        if not isinstance(at, (int, float)) or not 0.0 <= float(at) <= 1.0:
            raise LLMParseError(f"deck_position trigger: at must be in 0..1, got {at!r}")
        return DeckPosition(deck=int(deck), at=float(at))
    raise LLMParseError(f"unknown trigger type: {kind!r}")


def _payload_to_schedule(
    payload: dict[str, Any], *, original_text: str
) -> AgentSchedule:
    """Validate + convert the LLM's {schedule:[...]} payload into an
    AgentSchedule. Reuses _payload_to_plan for each step's plan body
    so the action-vocabulary validation stays single-sourced."""
    raw_steps = payload.get("schedule")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LLMParseError(f"schedule must be a non-empty list, got {raw_steps!r}")

    steps: list[ScheduledPlan] = []
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise LLMParseError(f"schedule step {i} is not an object: {raw!r}")
        trigger = _payload_to_trigger(raw.get("trigger", {}))
        label = str(raw.get("label", "")).strip() or f"step {i+1}"
        # Wrap the step's plan in the same shape _payload_to_plan
        # consumes so we get all of its validation for free.
        plan = _payload_to_plan(
            {"plan": raw.get("plan", [])}, original_text=original_text
        )
        steps.append(ScheduledPlan(trigger=trigger, plan=plan, label=label))

    return AgentSchedule(steps=tuple(steps))


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
            beats = int(payload["beats"])
            if beats not in LOOP_BEAT_SIZES:
                raise LLMParseError(
                    f"loop_deck beats must be one of {LOOP_BEAT_SIZES}, got {beats}"
                )
            return LoopDeck(deck=int(payload["deck"]), beats=beats)
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
        if name == "set_filter":
            return SetFilter(deck=int(payload["deck"]), value=float(payload["value"]))
        if name == "set_fx":
            unit = int(payload["unit"])
            if unit not in (1, 2):
                raise LLMParseError(f"set_fx unit must be 1 or 2, got {unit}")
            return SetFx(
                deck=int(payload["deck"]),
                unit=unit,  # type: ignore[arg-type]
                value=float(payload["value"]),
            )
        if name == "set_pitch":
            return SetPitch(deck=int(payload["deck"]), value=float(payload["value"]))
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
