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
    """A library track, projected for the UI."""

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
    """Returned in place of a runnable plan when the LLM emits LoadTrack.

    Mixxx 2.5/2.6 have no path-based load API (D-015), so LoadTrack is
    surfaced as a user-confirmed suggestion rather than executed.
    """

    track: TrackPayload
    deck: int
    reasoning: str


class ParseResponse(BaseModel):
    """What /parse returns.

    Carries either a runnable plan OR a suggestion (when the LLM picked
    a track for the user). `error` is set when parsing failed cleanly;
    HTTP 5xx covers unexpected failures.
    """

    text: str
    parsed: str
    conf: int
    affects: str
    source: Literal["regex", "llm"]
    plan: list[PlanStepPayload] = Field(default_factory=list)
    suggestion: SuggestionPayload | None = None
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
