"""Agent routes — POST /agent/start, POST /agent/cancel, GET /agent/state.

Receives an AgentSchedule from the frontend, hands it to the
AgentRuntime singleton, exposes the running schedule's state for the
UI's queue display.

See DECISIONS § D-021 for the agent-layer architecture + demo-scope.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from deckpilot.core.actions import ActionPlan, TimedAction
from deckpilot.core.agent import (
    AfterBeats,
    AgentSchedule,
    DeckPosition,
    Immediate,
    ScheduledPlan,
    Trigger,
)
from deckpilot.core.parser.llm import _payload_to_action

from ..models import (
    AgentSimpleResponse,
    AgentStartRequest,
    AgentStateResponse,
    AgentStepStatus,
    ScheduledPlanPayload,
    TriggerPayload,
)
from ..services.singletons import get_agent_runtime

router = APIRouter()


def _wire_trigger_to_core(p: TriggerPayload) -> Trigger:
    if p.type == "immediate":
        return Immediate()
    if p.type == "deck_position":
        if p.deck not in (1, 2):
            raise HTTPException(
                status_code=422,
                detail=f"deck_position trigger requires deck in (1,2); got {p.deck}",
            )
        if p.at is None or not 0.0 <= p.at <= 1.0:
            raise HTTPException(
                status_code=422,
                detail=f"deck_position trigger requires at in 0..1; got {p.at}",
            )
        return DeckPosition(deck=p.deck, at=p.at)
    if p.type == "after_beats":
        if p.deck not in (1, 2):
            raise HTTPException(
                status_code=422,
                detail=f"after_beats trigger requires deck in (1,2); got {p.deck}",
            )
        if p.count is None or not 1 <= p.count <= 256:
            raise HTTPException(
                status_code=422,
                detail=f"after_beats trigger requires count in 1..256; got {p.count}",
            )
        return AfterBeats(deck=p.deck, count=p.count)
    raise HTTPException(status_code=422, detail=f"unknown trigger type {p.type!r}")


def _wire_step_to_core(p: ScheduledPlanPayload) -> ScheduledPlan:
    """Convert one wire-format ScheduledPlanPayload into the core
    ScheduledPlan. Plan reconstruction reuses `_payload_to_action`
    from the LLM parser so the action schema stays single-sourced."""
    timed_actions: list[TimedAction] = []
    for step in p.plan:
        action = _payload_to_action(step.action, original_text="")
        timed_actions.append(TimedAction(action=action, at_seconds=step.at_seconds))

    return ScheduledPlan(
        trigger=_wire_trigger_to_core(p.trigger),
        plan=ActionPlan(steps=tuple(timed_actions)),
        label=p.label,
    )


@router.post("/agent/start", response_model=AgentSimpleResponse)
async def agent_start(req: AgentStartRequest) -> AgentSimpleResponse:
    runtime = get_agent_runtime()
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent runtime unavailable — MIDI / executor not initialised. "
                "Is Mixxx running and the IAC Driver enabled?"
            ),
        )

    if not req.schedule:
        return AgentSimpleResponse(success=False, error="empty schedule")

    try:
        steps = tuple(_wire_step_to_core(p) for p in req.schedule)
    except HTTPException:
        raise
    except Exception as exc:
        return AgentSimpleResponse(success=False, error=str(exc))

    await runtime.start(AgentSchedule(steps=steps))
    return AgentSimpleResponse(success=True)


@router.post("/agent/cancel", response_model=AgentSimpleResponse)
async def agent_cancel() -> AgentSimpleResponse:
    runtime = get_agent_runtime()
    if runtime is None:
        return AgentSimpleResponse(success=True)  # nothing to cancel
    await runtime.cancel()
    return AgentSimpleResponse(success=True)


@router.get("/agent/state", response_model=AgentStateResponse)
def agent_state() -> AgentStateResponse:
    runtime = get_agent_runtime()
    if runtime is None:
        return AgentStateResponse(active=False)

    snap = runtime.snapshot()
    return AgentStateResponse(
        active=snap.active,
        started_at_unix=snap.started_at_unix,
        steps=[
            AgentStepStatus(
                label=s.label,
                trigger_kind=s.trigger_kind,  # type: ignore[arg-type]
                trigger_deck=s.trigger_deck,
                trigger_at=s.trigger_at,
                trigger_count=s.trigger_count,
                remaining_count=s.remaining_count,
                signature=s.signature,
                affects=s.affects,
                status=s.status,  # type: ignore[arg-type]
            )
            for s in snap.steps
        ],
    )
