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
from deckpilot.core.agent import AgentSchedule, DeckPosition, Immediate
from deckpilot.core.parser import parse as facade_parse
from deckpilot.core.parser.errors import ParseError
from deckpilot.core.parser.regex import parse as regex_parse

from ..models import (
    ParseRequest,
    ParseResponse,
    PlanStepPayload,
    ScheduledPlanPayload,
    SuggestionPayload,
    TrackPayload,
    TriggerPayload,
)
from ..services.signatures import affects_label, render_action, summary_signature
from ..services.singletons import get_feedback, get_gui_adapter, get_library

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
    "SetFilter": "set_filter",
    "SetFx": "set_fx",
    "SetPitch": "set_pitch",
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


def schedule_to_payloads(schedule: AgentSchedule) -> list[ScheduledPlanPayload]:
    """AgentSchedule → list of ScheduledPlanPayload for the wire response.
    Mirror of plan_to_payloads but wraps each plan inside a trigger +
    label envelope. The frontend's AgentQueue consumes this verbatim."""
    out: list[ScheduledPlanPayload] = []
    for step in schedule.steps:
        if isinstance(step.trigger, Immediate):
            trig = TriggerPayload(type="immediate")
        elif isinstance(step.trigger, DeckPosition):
            trig = TriggerPayload(
                type="deck_position",
                deck=step.trigger.deck,
                at=step.trigger.at,
            )
        else:
            raise TypeError(f"unknown trigger: {step.trigger!r}")
        out.append(
            ScheduledPlanPayload(
                trigger=trig,
                plan=plan_to_payloads(step.plan),
                label=step.label,
            )
        )
    return out


@router.post("/parse", response_model=ParseResponse)
async def parse(req: ParseRequest) -> ParseResponse:
    library = get_library()
    feedback = get_feedback()
    deck_state = feedback.snapshot() if feedback is not None else None

    # Try regex first (fast-path, in-process, no LLM call). deck_state is
    # consulted by the "stop loop" rule so we fire the toggle matching the
    # active loop size (D-022 follow-up); forwarding it here keeps the
    # eager regex path on parity with the LLM path.
    if req.mode in ("auto", "regex"):
        regex_result = regex_parse(req.text, deck_state=deck_state)
        if regex_result is not None:
            return _build_response(req.text, regex_result, source="regex", library=library)
        if req.mode == "regex":
            # Sentinel — UI uses this to show the "press Enter to ask Haiku"
            # hint instead of an error toast. Not a real failure.
            return ParseResponse(
                text=req.text,
                parsed="",
                conf=0,
                affects="",
                source="regex",
                plan=[],
                error="no_regex_match",
            )

    # Fall through to the LLM. Wrap the blocking subprocess call so
    # FastAPI's event loop stays responsive.
    try:
        result = await asyncio.to_thread(
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

    # Schedule branch (D-021) — goal-style prompts get the agent shape
    # instead of a plain plan. The frontend routes schedules to
    # /agent/start instead of /execute.
    if isinstance(result, AgentSchedule):
        all_actions = [s.action for step in result.steps for s in step.plan.steps]
        return ParseResponse(
            text=req.text,
            parsed=summary_signature(all_actions) or "(agent schedule)",
            conf=95,
            affects=affects_label(all_actions),
            source="llm",
            plan=[],
            schedule=schedule_to_payloads(result),
        )

    plan = result  # type: ActionPlan

    # Special case: LLM picked a LoadTrack — surface a suggestion card
    # alongside the plan. Pre-D-019 we dropped the whole plan and forced
    # the user to drag. Now we keep the plan: if the GUI adapter is
    # wired AND the title+artist is unique in the library, /execute can
    # auto-fire the load. The UI uses `suggestion.auto_loadable` to
    # decide between the countdown UX and the manual-drag fallback.
    load_step = next(
        (s for s in plan.steps if isinstance(s.action, LoadTrack)),
        None,
    )
    if load_step is not None and library is not None:
        load = load_step.action
        track = library.get_by_id(load.track_id)
        if track is not None:
            query = f"{track.title} {track.artist}".strip()
            # Mirror the same uniqueness guard MidiAdapter applies, so
            # the UI knows upfront whether the auto-load will succeed.
            auto_loadable = (
                get_gui_adapter() is not None
                and library.count_search_matches(query) == 1
            )
            response = _build_response(req.text, plan, source="llm", library=library)
            response.suggestion = SuggestionPayload(
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
                auto_loadable=auto_loadable,
            )
            return response

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
