"""POST /parse/stream — Server-Sent Events parse.

Mirrors /parse but the response is a stream of events instead of a
single JSON blob. Used by the frontend's `usePilotFlow` for LLM
parses so plan steps reveal progressively in the UI as Haiku
generates them — perceived latency drops dramatically even though
absolute latency is roughly the same as the non-streaming path.

Regex parses don't use this — they're already instant. This route is
LLM-only (mode=llm semantics).

Event types emitted (one event per SSE block):
  - "started"  → fires immediately; signals subprocess spawned
  - "step"     → fires each time a complete plan-step JSON is parseable
                 (carries the wire-format PlanStepPayload)
  - "complete" → fires once with the full ParseResponse
                 (including suggestion handling for LoadTrack actions)
  - "error"    → fires on any failure path (timeout, decline, malformed)

SSE format:
  event: <type>
  data: <json>
  <blank line>
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from deckpilot.core.actions import ActionPlan, LoadTrack
from deckpilot.core.agent import AgentSchedule
from deckpilot.core.parser.llm_stream import stream_parse_llm

from ..models import ParseRequest, ParseResponse, SuggestionPayload, TrackPayload
from ..routes.parse import _build_response, action_to_dict, schedule_to_payloads
from ..services.signatures import affects_label, render_action, summary_signature
from ..services.singletons import get_feedback, get_gui_adapter, get_library

router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Events block. Each event is `event: <type>`
    + `data: <json-on-one-line>` + a blank line to delimit."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _wire_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw LLM step dict into a wire-format PlanStepPayload.

    The streaming side emits each step *as the LLM produced it* — that
    dict already matches the shape `_payload_to_action` consumes, plus
    optional `at`. We compute display fields (fn/detail/t/dMs) via the
    same `render_action` helper /parse uses, by first reconstructing
    the typed DJAction. Mirrors plan_to_payloads in parse.py."""
    from deckpilot.core.parser.llm import _payload_to_action

    action = _payload_to_action(raw_step, original_text="")
    fn, detail, t, dMs = render_action(action)
    return {
        "action": action_to_dict(action),
        "at_seconds": float(raw_step.get("at", 0.0)),
        "fn": fn,
        "detail": detail,
        "t": t,
        "dMs": dMs,
    }


@router.post("/parse/stream")
async def parse_stream(req: ParseRequest) -> StreamingResponse:
    """Stream an LLM parse. Regex is intentionally NOT consulted here —
    the frontend only calls this endpoint for paraphrases it knows
    regex can't handle (or after Enter on a no_regex_match)."""
    library = get_library()
    feedback = get_feedback()
    deck_state = feedback.snapshot() if feedback is not None else None

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_parse_llm(
            req.text, library=library, deck_state=deck_state
        ):
            kind = event["type"]

            if kind == "started":
                yield _sse("started", {})
                continue

            if kind == "step":
                # Best-effort conversion — if a step is malformed
                # (e.g. unknown action), skip it. The final 'complete'
                # event would fail anyway in that case, so the user
                # gets a clean error.
                try:
                    wire = _wire_step(event["step"])
                except Exception:
                    continue
                yield _sse("step", {"index": event["index"], "step": wire})
                continue

            if kind == "complete":
                # Branch on schedule vs plan — see D-021. Schedule
                # responses skip the suggestion-extraction step (which
                # was about lone LoadTrack actions) since schedules
                # are inherently multi-stage and execute autonomously.
                if "schedule" in event:
                    schedule: AgentSchedule = event["schedule"]
                    all_actions = [
                        s.action
                        for step in schedule.steps
                        for s in step.plan.steps
                    ]
                    schedule_response = ParseResponse(
                        text=req.text,
                        parsed=summary_signature(all_actions) or "(agent schedule)",
                        conf=95,
                        affects=affects_label(all_actions),
                        source="llm",
                        plan=[],
                        schedule=schedule_to_payloads(schedule),
                    )
                    yield _sse("complete", {"response": schedule_response.model_dump()})
                    continue

                plan: ActionPlan = event["plan"]
                response: ParseResponse = _build_response(
                    req.text, plan, source="llm", library=library
                )

                # Mirror the LoadTrack-suggestion logic from /parse so
                # the streaming path produces identical wire output to
                # the synchronous path. See parse.py for the rationale.
                load_step = next(
                    (s for s in plan.steps if isinstance(s.action, LoadTrack)),
                    None,
                )
                if load_step is not None and library is not None:
                    load = load_step.action
                    track = library.get_by_id(load.track_id)
                    if track is not None:
                        query = f"{track.title} {track.artist}".strip()
                        auto_loadable = (
                            get_gui_adapter() is not None
                            and library.count_search_matches(query) == 1
                        )
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

                # Wrap under `response` so the frontend's typed
                # ParseStreamEvent shape ({type, response}) matches.
                yield _sse("complete", {"response": response.model_dump()})
                continue

            if kind == "error":
                yield _sse("error", {"message": event["message"]})
                continue

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Tell intermediaries not to buffer; SSE depends on
            # immediate flush. Nginx/Cloudflare honour these.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
