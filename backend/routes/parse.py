"""POST /parse — text → ActionPlan.

Calls the existing two-tier parser facade
(`deckpilot.core.parser.parse`) with whatever runtime context is
available (library + live deck state). Falls through cleanly when those
aren't reachable.

The LLM call (`claude -p` subprocess) is sync + blocking, so we wrap
the whole parse call in `asyncio.to_thread` to keep the FastAPI event
loop responsive while the model thinks.

Returns the plan in the wire format the frontend's `usePilotFlow` will
consume directly (after Phase 4 rewires it).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, fields, is_dataclass

from fastapi import APIRouter

from deckpilot.adapters.midi import LoadTrackSuggestion
from deckpilot.core.actions import ActionPlan, DJAction, LoadTrack
from deckpilot.core.parser import parse as facade_parse
from deckpilot.core.parser.errors import ParseError
from deckpilot.core.parser.regex import parse as regex_parse

from ..models import (
    ParseRequest,
    ParseResponse,
    PlanStepPayload,
    SuggestionPayload,
    TrackPayload,
)
from ..services.signatures import affects_label, render_action, summary_signature
from ..services.singletons import get_feedback, get_library

router = APIRouter()


# Action name → snake_case mapping mirrored from llm.py so we can serialize
# the parsed plan back to a dict the frontend can later resend to /execute.
# Keep in sync with `deckpilot/core/parser/llm.py:_payload_to_action` (the
# reverse direction).
_ACTION_NAME = {
    "PlayDeck": "play_deck",
    "PauseDeck": "pause_deck",
    "SetCrossfader": "set_crossfader",
    "FadeToDeck": "fade_to_deck",
    "LoopDeck": "loop_deck",
    "NudgeDeck": "nudge_deck",
    "SetEQ": "set_eq",
    "SetVolume": "set_volume",
    "HotCue": "hot_cue",
    "Sync": "sync",
    "LoadTrack": "load_track",
}


def action_to_dict(action: DJAction) -> dict:
    """Serialize a frozen DJAction dataclass to the dict shape the parser
    accepts. Mirror of `_payload_to_action` but in reverse."""
    if not is_dataclass(action):
        raise TypeError(f"not a dataclass: {action!r}")
    payload = {"action": _ACTION_NAME[type(action).__name__]}
    for f in fields(action):
        payload[f.name] = getattr(action, f.name)
    return payload


def plan_to_payloads(plan: ActionPlan) -> list[PlanStepPayload]:
    """ActionPlan → list of PlanStepPayload for the wire response."""
    payloads = []
    for step in plan.steps:
        fn, detail, t, dMs = render_action(step.action)
        payloads.append(
            PlanStepPayload(
                action=action_to_dict(step.action),
                at_seconds=step.at_seconds,
                fn=fn,
                detail=detail,
                t=t,
                dMs=dMs,
            )
        )
    return payloads


@router.post("/parse", response_model=ParseResponse)
async def parse(req: ParseRequest) -> ParseResponse:
    library = get_library()
    feedback = get_feedback()
    deck_state = feedback.snapshot() if feedback is not None else None

    # Try regex first (fast-path, in-process, no LLM call).
    regex_result = regex_parse(req.text)
    if regex_result is not None:
        return _build_response(req.text, regex_result, source="regex", library=library)

    # Fall through to the LLM. Wrap the blocking subprocess call so
    # FastAPI's event loop stays responsive.
    try:
        plan = await asyncio.to_thread(
            facade_parse, req.text, library=library, deck_state=deck_state, mode="llm"
        )
    except ParseError as exc:
        return ParseResponse(
            text=req.text,
            parsed="(declined)",
            conf=0,
            affects="—",
            source="llm",
            plan=[],
            error=str(exc),
        )

    # Special case: LLM picked a LoadTrack — surface as a suggestion card.
    # The single LoadTrack step doesn't run; subsequent steps would target
    # an unloaded deck so we drop the whole plan and return the suggestion.
    load_step = next(
        (s for s in plan.steps if isinstance(s.action, LoadTrack)),
        None,
    )
    if load_step is not None and library is not None:
        load = load_step.action
        track = library.get_by_id(load.track_id)
        if track is not None:
            return ParseResponse(
                text=req.text,
                parsed=f"library.suggest(deck:{load.deck}, id:{load.track_id})",
                conf=95,
                affects=f"deck {load.deck}",
                source="llm",
                plan=[],  # nothing to execute
                suggestion=SuggestionPayload(
                    track=TrackPayload(
                        id=track.id,
                        artist=track.artist,
                        title=track.title,
                        bpm=track.bpm,
                        key=track.key,
                        genre=track.genre,
                    ),
                    deck=load.deck,
                    reasoning=load.reasoning,
                ),
            )

    return _build_response(req.text, plan, source="llm", library=library)


def _build_response(
    text: str,
    plan: ActionPlan,
    *,
    source: str,
    library,
) -> ParseResponse:
    actions = [s.action for s in plan.steps]
    return ParseResponse(
        text=text,
        parsed=summary_signature(actions),
        conf=99 if source == "regex" else 95,
        affects=affects_label(actions),
        source=source,  # type: ignore[arg-type]
        plan=plan_to_payloads(plan),
    )
