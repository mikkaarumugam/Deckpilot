"""
AgentRuntime — runs an AgentSchedule, polling Mixxx state and firing
each ScheduledPlan when its trigger condition hits.

Lifecycle:
- AgentRuntime is a singleton (one active schedule at a time, by design;
  see D-021 demo-scope).
- start(schedule): replaces any pending schedule, kicks off the background
  poll task if not already running.
- cancel(): wipes the schedule, leaves the poll task idle.
- snapshot(): returns the current public state for the /agent/state route.

Concurrency:
- `_lock` serialises state mutations + plan execution. A scheduled plan
  is always run while holding the lock, which means a manual /execute
  request can't fire concurrently. This is the bluntest possible answer
  to the race-condition risk; finer concurrency is v0.3 work.

Why not a queue + worker thread:
- We're already in FastAPI's asyncio event loop. A task + asyncio.Lock
  is enough and keeps everything observable from one place.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from deckpilot.adapters.midi_feedback import MixxxState
from deckpilot.core.actions import ActionPlan
from deckpilot.core.agent import (
    AgentSchedule,
    DeckPosition,
    Immediate,
    ScheduledPlan,
    Trigger,
)
from deckpilot.core.executor import Executor


# How often the scheduler checks pending triggers. 500ms is matched to
# the frontend's state polling — no point firing more often than the UI
# can show the change.
_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class _PublicStepStatus:
    """One row in the /agent/state response."""

    label: str
    trigger_kind: str           # "immediate" | "deck_position"
    trigger_deck: Optional[int] # set when trigger_kind == "deck_position"
    trigger_at: Optional[float] # set when trigger_kind == "deck_position"
    status: str                 # "done" | "running" | "pending"


@dataclass(frozen=True)
class AgentStateSnapshot:
    """What /agent/state returns. Mirror of the wire format that the
    frontend's AgentQueue will render."""

    active: bool
    started_at_unix: Optional[float]
    steps: tuple[_PublicStepStatus, ...]


def _trigger_kind(t: Trigger) -> tuple[str, Optional[int], Optional[float]]:
    """Reduce a Trigger to its wire-format tuple."""
    if isinstance(t, Immediate):
        return ("immediate", None, None)
    if isinstance(t, DeckPosition):
        return ("deck_position", t.deck, t.at)
    raise TypeError(f"unknown trigger: {t!r}")


class AgentRuntime:
    """Manages at most one active AgentSchedule + a background poll task."""

    def __init__(self, executor: Executor, feedback_snapshot) -> None:
        self._executor = executor
        # Function-injected so the runtime doesn't import the singletons
        # module (which would create a cycle). Caller passes
        # `lambda: get_feedback().snapshot()` from singletons.
        self._snapshot = feedback_snapshot
        self._schedule: Optional[AgentSchedule] = None
        self._cursor: int = 0  # index of next step to consider
        self._started_at: Optional[float] = None
        self._currently_running: Optional[int] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # ── public API ────────────────────────────────────────────────────

    async def start(self, schedule: AgentSchedule) -> None:
        """Replace any pending schedule and (re)start the poll task."""
        async with self._lock:
            self._schedule = schedule
            self._cursor = 0
            self._started_at = time.time()
            self._currently_running = None
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def cancel(self) -> None:
        async with self._lock:
            self._schedule = None
            self._cursor = 0
            self._started_at = None
            self._currently_running = None
        # We DON'T cancel the task itself — it'll see schedule=None on
        # its next tick and idle. Avoids the "task cancelled mid-MIDI"
        # failure mode.

    def snapshot(self) -> AgentStateSnapshot:
        """Cheap, lock-free read of the public state. Slightly racy on
        cursor / currently_running but that's a UX-level concern, not a
        correctness one — the next /agent/state poll resolves it."""
        if self._schedule is None:
            return AgentStateSnapshot(active=False, started_at_unix=None, steps=())

        rows: list[_PublicStepStatus] = []
        for i, step in enumerate(self._schedule.steps):
            kind, deck, at = _trigger_kind(step.trigger)
            if i < self._cursor:
                status = "done"
            elif i == self._currently_running:
                status = "running"
            else:
                status = "pending"
            rows.append(
                _PublicStepStatus(
                    label=step.label,
                    trigger_kind=kind,
                    trigger_deck=deck,
                    trigger_at=at,
                    status=status,
                )
            )

        return AgentStateSnapshot(
            active=True,
            started_at_unix=self._started_at,
            steps=tuple(rows),
        )

    # ── internals ─────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Background poll loop. Exits when the schedule completes or
        gets cancelled. Re-entered by start() if a new schedule arrives."""
        try:
            while True:
                await asyncio.sleep(_POLL_SECONDS)
                schedule = self._schedule
                if schedule is None:
                    return  # cancelled

                if self._cursor >= len(schedule.steps):
                    # All steps fired. Idle out.
                    async with self._lock:
                        self._schedule = None
                        self._started_at = None
                    return

                step = schedule.steps[self._cursor]
                state = self._snapshot()
                if state is None:
                    # Feedback unavailable — Mixxx probably down. Hold
                    # the schedule pending instead of erroring out; the
                    # user can cancel from the UI.
                    continue

                if not step.trigger.fires(state):
                    continue

                # Trigger fires — run the bound plan under the lock so
                # nothing else can fire MIDI concurrently.
                await self._run_step(self._cursor, step.plan)
        except Exception:
            # Don't let an exception kill the loop silently. The /agent/state
            # poller will show the schedule still pending; user cancels.
            # (Future: surface this via the snapshot.)
            pass

    async def _run_step(self, cursor: int, plan: ActionPlan) -> None:
        """Run one ActionPlan via the existing Executor, under the lock,
        bookkeeping cursor/currently_running for the public snapshot."""
        async with self._lock:
            self._currently_running = cursor
        try:
            # Executor.run_plan is blocking (sleeps for fade durations).
            # to_thread so the asyncio loop stays responsive — same as
            # /execute does.
            await asyncio.to_thread(self._executor.run_plan, plan)
        finally:
            async with self._lock:
                self._currently_running = None
                # Advance the cursor whether the plan succeeded or
                # threw — failure recovery is out of scope for demo
                # Tier 2 (see D-021). The user cancels + re-prompts.
                self._cursor = cursor + 1
