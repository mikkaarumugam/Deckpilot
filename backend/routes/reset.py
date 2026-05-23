"""POST /reset — bring Mixxx back to neutral.

Pauses both decks, centres the crossfader, restores EQs and volumes.
The plan itself is computed by `deckpilot.core.undo.reset_plan`. We run
it through the same Executor.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from deckpilot.core.undo import reset_plan

from ..models import UndoResponse
from ..routes.parse import plan_to_payloads
from ..services.singletons import get_executor

router = APIRouter()


@router.post("/reset", response_model=UndoResponse)
async def reset() -> UndoResponse:
    executor = get_executor()
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail="MIDI adapter unavailable.",
        )

    plan = reset_plan()
    try:
        await asyncio.to_thread(executor.run_plan, plan)
    except Exception as exc:
        return UndoResponse(success=False, error=str(exc))

    return UndoResponse(
        success=True,
        inverted_plan=plan_to_payloads(plan),
    )
