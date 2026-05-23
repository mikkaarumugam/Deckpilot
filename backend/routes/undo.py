"""POST /undo — invert a plan and run the inverse.

Calls `deckpilot.core.undo.inverse_plan` on the plan the frontend sends
(it kept the original ParseResponse in component state). Some actions
have no clean inverse (Sync, HotCue, NudgeDeck) — for those
`inverse_plan` returns None and we surface that as a graceful failure.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from deckpilot.core.undo import inverse_plan

from ..models import PlanStepPayload, UndoRequest, UndoResponse
from ..routes.execute import payload_to_plan
from ..routes.parse import plan_to_payloads
from ..services.singletons import get_executor

router = APIRouter()


@router.post("/undo", response_model=UndoResponse)
async def undo(req: UndoRequest) -> UndoResponse:
    executor = get_executor()
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail="MIDI adapter unavailable.",
        )

    plan = payload_to_plan(req.plan)
    inverse = inverse_plan(plan)
    if inverse is None:
        return UndoResponse(
            success=False,
            error="This command can't be cleanly undone.",
        )

    try:
        await asyncio.to_thread(executor.run_plan, inverse)
    except Exception as exc:
        return UndoResponse(success=False, error=str(exc))

    return UndoResponse(
        success=True,
        inverted_plan=plan_to_payloads(inverse),
    )
