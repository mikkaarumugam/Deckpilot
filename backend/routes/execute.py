"""POST /execute — run a parsed plan.

Reconstructs `DJAction` instances from the dict payloads via the
existing `_payload_to_action` helper, wraps them in `TimedAction`s,
runs the resulting `ActionPlan` through the existing Executor.

If a LoadTrack in the plan can't auto-load (no GUI adapter, library
unavailable, or the title+artist is ambiguous), the adapter raises
`LoadTrackSuggestion` (see D-015 / D-019). We catch it and return a
200 with the suggestion payload + `auto_loadable: false` — the
frontend then falls back to the manual-drag suggestion card.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException

from deckpilot.adapters.midi import LoadTrackSuggestion
from deckpilot.core.actions import ActionPlan, TimedAction
from deckpilot.core.parser.llm import _payload_to_action

from ..models import (
    ExecuteRequest,
    ExecuteResponse,
    PlanStepPayload,
    SuggestionPayload,
    TrackPayload,
)
from ..services.singletons import get_executor

router = APIRouter()


def payload_to_plan(steps: list[PlanStepPayload]) -> ActionPlan:
    """Inverse of plan_to_payloads — reconstruct an ActionPlan from the
    wire format. Reuses `_payload_to_action` from the LLM parser so the
    reconstruction logic stays single-sourced."""
    timed = []
    for step in steps:
        action = _payload_to_action(step.action, original_text="")
        timed.append(TimedAction(action=action, at_seconds=step.at_seconds))
    return ActionPlan(steps=tuple(timed))


@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    executor = get_executor()
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "MIDI adapter unavailable. Is Mixxx running and the "
                "IAC Driver enabled? See docs/GOTCHAS.md."
            ),
        )

    plan = payload_to_plan(req.plan)

    start = time.monotonic()
    try:
        # Wrap the blocking run_plan in to_thread — long fades sleep for
        # multiple seconds; we don't want to block the event loop.
        await asyncio.to_thread(executor.run_plan, plan)
    except LoadTrackSuggestion as sug:
        # Reaching this branch means the adapter declined auto-load
        # (no GUI adapter, no library, or library uniqueness failed).
        # Surface a suggestion with auto_loadable=False so the UI shows
        # the manual-drag fallback instead of looping the countdown.
        elapsed_ms = int((time.monotonic() - start) * 1000)
        track = sug.track
        payload = None
        if track is not None:
            payload = SuggestionPayload(
                track=TrackPayload(
                    id=track.id,
                    artist=track.artist,
                    title=track.title,
                    bpm=track.bpm,
                    key=track.key,
                    genre=track.genre,
                ),
                deck=sug.action.deck,
                reasoning=sug.action.reasoning,
                auto_loadable=False,
            )
        return ExecuteResponse(
            success=True,
            elapsed_ms=elapsed_ms,
            suggestion=payload,
        )
    except Exception as exc:
        return ExecuteResponse(
            success=False,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            error=str(exc),
        )

    return ExecuteResponse(
        success=True,
        elapsed_ms=int((time.monotonic() - start) * 1000),
    )
