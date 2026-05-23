"""
Unit tests for the agent layer (D-021 + D-023).

Covers:
  - Trigger.fires() semantics for each of the three trigger types,
    including the baseline parameter that AfterBeats needs.
  - LLM validator round-trips for the trigger JSON shape — making
    sure the parser rejects out-of-range or malformed payloads.
  - AgentRuntime baseline capture: the first poll on a new cursor
    must snapshot state; subsequent polls must compare against that
    same snapshot.

Mixxx + MIDI are not exercised here. We mock MixxxState directly
since the trigger semantics are a pure function of state.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Optional

import pytest

from deckpilot.adapters.midi_feedback import DeckState, MixxxState
from deckpilot.core.actions import ActionPlan, PlayDeck, TimedAction
from deckpilot.core.agent import (
    AfterBeats,
    AgentSchedule,
    DeckPosition,
    Immediate,
    ScheduledPlan,
)
from deckpilot.core.parser.llm import LLMParseError, _payload_to_trigger


def _state(deck: int = 1, **kwargs) -> MixxxState:
    """Build a MixxxState with one deck overridden. Defaults for the
    other deck keep the snapshot complete."""
    other = 2 if deck == 1 else 1
    return MixxxState(decks={deck: DeckState(**kwargs), other: DeckState()})


# ── Trigger.fires() ──────────────────────────────────────────────────────


def test_immediate_always_fires() -> None:
    assert Immediate().fires(_state()) is True
    # Baseline is ignored — passing one shouldn't change anything.
    assert Immediate().fires(_state(), _state()) is True


@pytest.mark.parametrize("position, at, expected", [
    (0.0, 0.5, False),
    (0.49, 0.5, False),
    (0.5, 0.5, True),
    (0.92, 0.92, True),
    (1.0, 0.92, True),
])
def test_deck_position_fires_at_threshold(
    position: float, at: float, expected: bool
) -> None:
    state = _state(deck=1, position=position)
    assert DeckPosition(deck=1, at=at).fires(state) is expected


def test_after_beats_needs_baseline() -> None:
    # Without a baseline AfterBeats refuses to fire — the runtime always
    # provides one in practice, so this is a defensive guard for tests
    # or misuse rather than a path the runtime would take.
    assert AfterBeats(deck=1, count=4).fires(_state(beat_count=100)) is False


def test_after_beats_fires_on_threshold() -> None:
    trigger = AfterBeats(deck=1, count=4)
    baseline = _state(deck=1, beat_count=100)

    # Same beat count — no beats have elapsed yet.
    assert trigger.fires(_state(deck=1, beat_count=100), baseline) is False
    # 3 beats elapsed — still below the threshold.
    assert trigger.fires(_state(deck=1, beat_count=103), baseline) is False
    # 4 beats elapsed — exactly at the threshold, fires.
    assert trigger.fires(_state(deck=1, beat_count=104), baseline) is True
    # 5+ beats elapsed — still fires.
    assert trigger.fires(_state(deck=1, beat_count=105), baseline) is True


def test_after_beats_counts_only_specified_deck() -> None:
    # Beats on the OTHER deck don't move our counter — important when
    # one deck is paused and the other is still ticking.
    trigger = AfterBeats(deck=1, count=4)
    baseline = MixxxState(decks={
        1: DeckState(beat_count=100),
        2: DeckState(beat_count=100),
    })
    # Deck 1 unchanged, deck 2 ticked 8 beats. Still shouldn't fire.
    state = MixxxState(decks={
        1: DeckState(beat_count=100),
        2: DeckState(beat_count=108),
    })
    assert trigger.fires(state, baseline) is False


# ── LLM trigger validator ────────────────────────────────────────────────


def test_validator_accepts_immediate() -> None:
    assert _payload_to_trigger({"type": "immediate"}) == Immediate()


def test_validator_accepts_deck_position() -> None:
    got = _payload_to_trigger({"type": "deck_position", "deck": 1, "at": 0.5})
    assert got == DeckPosition(deck=1, at=0.5)


def test_validator_accepts_after_beats() -> None:
    got = _payload_to_trigger({"type": "after_beats", "deck": 2, "count": 16})
    assert got == AfterBeats(deck=2, count=16)


@pytest.mark.parametrize("payload, reason", [
    ({"type": "after_beats", "deck": 0, "count": 4}, "bad deck"),
    ({"type": "after_beats", "deck": 1, "count": 0}, "count < 1"),
    ({"type": "after_beats", "deck": 1, "count": 300}, "count > 256"),
    ({"type": "after_beats", "deck": 1, "count": 4.5}, "count not int"),
    ({"type": "after_beats", "deck": 1}, "count missing"),
    ({"type": "weird"}, "unknown type"),
])
def test_validator_rejects_bad_triggers(payload: dict, reason: str) -> None:
    with pytest.raises(LLMParseError):
        _payload_to_trigger(payload)


# ── AgentRuntime baseline behavior ───────────────────────────────────────
#
# We test the runtime's `_loop` behavior indirectly by driving it with a
# scripted snapshot source. The Executor is mocked so no MIDI gets sent.


class _FakeExecutor:
    """Stand-in for the real Executor — just records what gets run."""

    def __init__(self) -> None:
        self.runs: list[ActionPlan] = []

    def run_plan(self, plan: ActionPlan) -> None:
        self.runs.append(plan)


def _drive_runtime(
    states: list[MixxxState],
    schedule: AgentSchedule,
    poll_seconds: float = 0.0,
) -> _FakeExecutor:
    """Walk an AgentRuntime through a scripted state sequence. Each
    element of `states` is the snapshot returned on the next poll. The
    loop runs until the schedule completes or we run out of states.

    Uses poll_seconds≈0 + asyncio.sleep(0) yields so a multi-step test
    finishes instantly without timing flakiness."""
    from backend.services import agent_runtime as ar_module
    from backend.services.agent_runtime import AgentRuntime

    # Patch the module's poll interval so the test doesn't have to wait.
    original_poll = ar_module._POLL_SECONDS
    ar_module._POLL_SECONDS = poll_seconds

    states_iter = iter(states)
    last_state = states[-1] if states else None

    def snapshot() -> Optional[MixxxState]:
        nonlocal last_state
        try:
            last_state = next(states_iter)
        except StopIteration:
            pass
        return last_state

    executor = _FakeExecutor()
    runtime = AgentRuntime(executor, snapshot)  # type: ignore[arg-type]

    async def go() -> None:
        await runtime.start(schedule)
        # Yield control until the runtime's task finishes (it self-terminates
        # when the schedule completes). Cap iterations to avoid infinite
        # loop if the test is misconfigured.
        for _ in range(200):
            await asyncio.sleep(0)
            if runtime._task is None or runtime._task.done():
                break

    try:
        asyncio.run(go())
    finally:
        ar_module._POLL_SECONDS = original_poll

    return executor


def test_runtime_fires_immediate_step() -> None:
    plan = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=1)),))
    schedule = AgentSchedule(steps=(
        ScheduledPlan(trigger=Immediate(), plan=plan, label="kickoff"),
    ))
    executor = _drive_runtime([_state()], schedule)
    assert len(executor.runs) == 1
    assert executor.runs[0] is plan


def test_runtime_after_beats_captures_baseline_then_fires() -> None:
    """AfterBeats(count=4) should NOT fire on the first poll (baseline
    capture only). On subsequent polls it should compare against the
    captured baseline and fire when the threshold is hit."""
    plan = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=1)),))
    schedule = AgentSchedule(steps=(
        ScheduledPlan(
            trigger=AfterBeats(deck=1, count=4),
            plan=plan,
            label="in 4 beats",
        ),
    ))

    # Poll 1: beat_count=100 → baseline. Poll 2: 102 (no fire). Poll 3:
    # 104 (fires).
    states = [
        _state(deck=1, beat_count=100),
        _state(deck=1, beat_count=102),
        _state(deck=1, beat_count=104),
    ]
    executor = _drive_runtime(states, schedule)
    assert len(executor.runs) == 1


def test_runtime_after_beats_uses_FIRST_poll_as_baseline_not_start() -> None:
    """If beat_count has already advanced between start() and the first
    poll, the runtime uses the FIRST POLL's value as baseline — that's
    the moment the step entered 'pending' from the runtime's view."""
    plan = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=1)),))
    schedule = AgentSchedule(steps=(
        ScheduledPlan(
            trigger=AfterBeats(deck=1, count=4),
            plan=plan,
            label="in 4 beats",
        ),
    ))
    # Baseline gets captured at 200. Need to reach 204 to fire.
    states = [
        _state(deck=1, beat_count=200),  # baseline
        _state(deck=1, beat_count=203),  # not yet (3 beats elapsed)
        _state(deck=1, beat_count=204),  # fires
    ]
    executor = _drive_runtime(states, schedule)
    assert len(executor.runs) == 1


def test_runtime_each_step_gets_its_own_baseline() -> None:
    """Two AfterBeats steps in a row — the second step's baseline must
    be captured when the FIRST step finishes, not at schedule start."""
    plan1 = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=1)),))
    plan2 = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=2)),))
    schedule = AgentSchedule(steps=(
        ScheduledPlan(trigger=AfterBeats(deck=1, count=2), plan=plan1, label="step 1"),
        ScheduledPlan(trigger=AfterBeats(deck=1, count=2), plan=plan2, label="step 2"),
    ))
    # Loop step-by-step:
    #   poll 1: snapshot=100 → step1 baseline=100, 0 elapsed, no fire
    #   poll 2: snapshot=102 → 2 elapsed ≥ 2 → step1 fires, cursor→1
    #   poll 3: snapshot=103 → step2 baseline=103, 0 elapsed, no fire
    #   poll 4: snapshot=104 → 1 elapsed, no fire
    #   poll 5: snapshot=105 → 2 elapsed ≥ 2 → step2 fires
    states = [
        _state(deck=1, beat_count=100),
        _state(deck=1, beat_count=102),
        _state(deck=1, beat_count=103),
        _state(deck=1, beat_count=104),
        _state(deck=1, beat_count=105),
    ]
    executor = _drive_runtime(states, schedule)
    assert len(executor.runs) == 2


def test_runtime_remaining_count_decrements_with_beats() -> None:
    """Snapshot's remaining_count should reflect the live progress while
    the after_beats step is pending."""
    from backend.services.agent_runtime import AgentRuntime

    plan = ActionPlan(steps=(TimedAction(action=PlayDeck(deck=1)),))
    schedule = AgentSchedule(steps=(
        ScheduledPlan(
            trigger=AfterBeats(deck=1, count=8),
            plan=plan,
            label="in 8 beats",
        ),
    ))

    state = _state(deck=1, beat_count=50)

    def snapshot() -> MixxxState:
        return state

    runtime = AgentRuntime(_FakeExecutor(), snapshot)  # type: ignore[arg-type]

    async def go():
        nonlocal state
        await runtime.start(schedule)
        # Without driving the loop, no baseline is captured yet — the UI
        # should still show the full count.
        snap = runtime.snapshot()
        assert snap.steps[0].remaining_count == 8

        # Manually plant the baseline as the loop would (avoids needing
        # to chase async timing in a test).
        async with runtime._lock:
            runtime._step_baselines[0] = state

        # Advance 3 beats → 5 remaining.
        state = replace(state, decks={
            1: DeckState(beat_count=53),
            2: DeckState(),
        })
        snap = runtime.snapshot()
        assert snap.steps[0].remaining_count == 5

        # Advance past the threshold → 0 remaining (never negative).
        state = replace(state, decks={
            1: DeckState(beat_count=100),
            2: DeckState(),
        })
        snap = runtime.snapshot()
        assert snap.steps[0].remaining_count == 0

        await runtime.cancel()

    asyncio.run(go())
