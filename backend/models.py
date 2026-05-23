"""Pydantic models — the HTTP wire format between React and Python.

Design rule: each model maps one-to-one to a type the frontend's
`types.ts` already declares. When the React side adds a field, this file
gets a matching field; when this file adds a field, types.ts follows.

The action wire format intentionally mirrors what the existing LLM parser
already emits (a flat dict with an "action" discriminator + the action's
own fields), so the same `_payload_to_action` helper from
`deckpilot.core.parser.llm` reconstructs `DJAction` instances on the
`/execute` side. Keeps the reconstruction logic single-sourced.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Track + deck state ────────────────────────────────────────────────────


class TrackPayload(BaseModel):
    """A library track, projected for the UI.

    Note: artwork isn't an explicit field — the UI always renders
    <img src="/artwork/{id}"/> with an onError handler that falls back
    to a placeholder. Cleaner than probing the file from this hot-path
    serializer; the browser caches the 404 after the first miss.
    """

    id: int
    artist: str
    title: str
    bpm: float
    key: str
    genre: str


class ProgressPayload(BaseModel):
    """Track position within the currently-loaded track on a deck.

    Without playhead read-back (deferred — see Thread 4 in AGENT_DESIGN.md)
    we don't have a real `t` value for the current playhead position; only
    the loaded track's total duration. Frontend treats `pct` as a hint
    rather than ground truth.
    """

    t: str = "—"
    total: str = "—"
    pct: float = 0.0


class DeckStatePayload(BaseModel):
    n: Literal[1, 2]
    status: Literal["playing", "paused", "cued"]
    bpm: float
    track: TrackPayload | None = None
    progress: ProgressPayload = Field(default_factory=ProgressPayload)
    # Monotonic beat counter from MixxxFeedback (one tick per `beat_active`
    # rising edge). Frontend uses this for the agent queue's beat
    # countdown — sees that the deck is "alive" beat-wise even when no
    # schedule is running. Defaults to 0 when feedback is unavailable.
    beat_count: int = 0


class StateResponse(BaseModel):
    """Snapshot returned from GET /state. Polled by the frontend at ~250ms."""

    decks: list[DeckStatePayload]
    crossfade: float | None = None
    bpm_delta: float | None = None


# ── Plan + parse ──────────────────────────────────────────────────────────


class PlanStepPayload(BaseModel):
    """One step in the plan, as both /parse emits and /execute consumes.

    The `action` field is a raw dict matching what
    `deckpilot.core.parser.llm._payload_to_action` accepts:
    `{"action": "play_deck", "deck": 1, ...}`. Same shape the LLM emits,
    so the reconstruction logic stays single-sourced.

    The four UI-facing fields (fn, detail, t, dMs) are computed by
    `backend.services.signatures` from the DJAction so the React side
    never has to know about any action's internals.
    """

    action: dict[str, Any]
    at_seconds: float = 0.0

    # UI-facing display fields, computed by the backend on parse:
    fn: str
    detail: str
    t: str
    dMs: int


class SuggestionPayload(BaseModel):
    """Returned alongside a plan that contains a LoadTrack action.

    Carries the chosen track + LLM reasoning for the UI to render as a
    preview card. `auto_loadable` indicates whether the backend can
    actually execute the load via the GUI adapter (D-019) — true means
    the UI shows a countdown + auto-fires /execute; false means it
    falls back to the manual-drag hint (the original D-015 behaviour).
    """

    track: TrackPayload
    deck: int
    reasoning: str
    # True when the GUI adapter is wired AND the library uniqueness
    # check passes (title+artist match exactly one library row). False
    # otherwise — UI then shows the "drag manually" hint and the plan
    # won't auto-fire. See deckpilot/adapters/midi.py:_dispatch_load_track
    # for the equivalent server-side guard.
    auto_loadable: bool = False


class ParseResponse(BaseModel):
    """What /parse returns.

    Carries either a runnable plan, a suggestion (LoadTrack), OR an
    agent schedule (goal-style prompt; D-021). Exactly one of `plan`
    or `schedule` is populated for any given response. The frontend
    routes schedules to /agent/start instead of /execute.
    """

    text: str
    parsed: str
    conf: int
    affects: str
    source: Literal["regex", "llm"]
    plan: list[PlanStepPayload] = Field(default_factory=list)
    suggestion: SuggestionPayload | None = None
    # Populated when the LLM emitted a goal-style schedule. None for
    # ordinary single-shot plans. See D-021 for the design.
    schedule: list[ScheduledPlanPayload] | None = None
    error: str | None = None


class ParseRequest(BaseModel):
    text: str
    # mode="auto" (default) runs regex first, falls through to LLM.
    # mode="regex" runs only the regex parser — used by the frontend's
    # eager-on-each-keystroke flow so we don't spawn an LLM subprocess
    # for every character typed. Returns error="no_regex_match" sentinel
    # if regex doesn't hit, so the UI can render a "press Enter to ask
    # Haiku" hint without treating it as a real failure.
    # mode="llm" skips regex (rarely needed).
    mode: Literal["auto", "regex", "llm"] = "auto"


# ── Execute / undo / reset ───────────────────────────────────────────────


class ExecuteRequest(BaseModel):
    """Re-send the plan we got from /parse, so /execute doesn't have to
    re-parse text. Frontend caches the ParseResponse in component state."""

    plan: list[PlanStepPayload]


class ExecuteResponse(BaseModel):
    success: bool
    elapsed_ms: int
    error: str | None = None
    suggestion: SuggestionPayload | None = None


class UndoRequest(BaseModel):
    """Plan to invert. Frontend sends the original plan; backend computes
    the inverse via `deckpilot.core.undo.inverse_plan`."""

    plan: list[PlanStepPayload]


class UndoResponse(BaseModel):
    success: bool
    inverted_plan: list[PlanStepPayload] | None = None
    error: str | None = None


# ── Agent (D-021: goal-directed schedules) ────────────────────────────────


class TriggerPayload(BaseModel):
    """Wire format for a trigger. `type` is the discriminator:
      - immediate     → no extra fields
      - deck_position → deck + at (0..1)
      - after_beats   → deck + count (≥1, beats from when the step
                        became pending; see D-023)
    """

    type: Literal["immediate", "deck_position", "after_beats"]
    deck: int | None = None
    at: float | None = None
    count: int | None = None


class ScheduledPlanPayload(BaseModel):
    """One entry in an AgentSchedule: trigger + plan to run when it fires."""

    trigger: TriggerPayload
    plan: list[PlanStepPayload]
    label: str


class AgentStartRequest(BaseModel):
    schedule: list[ScheduledPlanPayload]


class AgentStepStatus(BaseModel):
    """One row in the /agent/state response — what the UI's queue shows."""

    label: str
    trigger_kind: Literal["immediate", "deck_position", "after_beats"]
    trigger_deck: int | None = None
    trigger_at: float | None = None
    # For after_beats: total beats requested + how many are still to go.
    # remaining_count is computed server-side using the per-step baseline
    # so the UI doesn't need access to the snapshot; once the step is
    # running/done it's None.
    trigger_count: int | None = None
    remaining_count: int | None = None
    status: Literal["done", "running", "pending"]


class AgentStateResponse(BaseModel):
    active: bool
    started_at_unix: float | None = None
    steps: list[AgentStepStatus] = Field(default_factory=list)


class AgentSimpleResponse(BaseModel):
    """For /agent/start + /agent/cancel — just success + optional error."""

    success: bool
    error: str | None = None
