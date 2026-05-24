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
    AfterBeats,
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
    trigger_kind: str           # "immediate" | "deck_position" | "after_beats"
    trigger_deck: Optional[int] # populated for deck_position + after_beats
    trigger_at: Optional[float] # populated for deck_position
    trigger_count: Optional[int]   # populated for after_beats (total beats)
    remaining_count: Optional[int] # populated for after_beats (beats to go)
    # Plan summary signature for the inner ActionPlan — same shape the
    # CommandCard's PlanStep uses for its `fn` field. Lets the
    # AgentQueue UI render with the same rail+node + monospace
    # signature visual as the regular plan timeline.
    signature: str
    affects: str
    status: str                 # "done" | "running" | "pending"


@dataclass(frozen=True)
class AgentStateSnapshot:
    """What /agent/state returns. Mirror of the wire format that the
    frontend's AgentQueue will render."""

    active: bool
    started_at_unix: Optional[float]
    steps: tuple[_PublicStepStatus, ...]


def _trigger_kind(
    t: Trigger,
) -> tuple[str, Optional[int], Optional[float], Optional[int]]:
    """Reduce a Trigger to its wire-format tuple
    (kind, deck, at, count)."""
    if isinstance(t, Immediate):
        return ("immediate", None, None, None)
    if isinstance(t, DeckPosition):
        return ("deck_position", t.deck, t.at, None)
    if isinstance(t, AfterBeats):
        return ("after_beats", t.deck, None, t.count)
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
        # Per-step baseline snapshot. AfterBeats triggers need to know
        # "what was the beat counter when this step BECAME PENDING" —
        # snapshotted on the first poll where the step is current, reused
        # on every subsequent poll until it fires or the cursor advances.
        # Keyed by cursor index so the snapshot stays correct even if
        # the runtime restarts a step (it doesn't today, but the keying
        # is the safer invariant).
        self._step_baselines: dict[int, MixxxState] = {}

    # ── public API ────────────────────────────────────────────────────

    async def start(self, schedule: AgentSchedule) -> None:
        """Replace any pending schedule and (re)start the poll task."""
        async with self._lock:
            self._schedule = schedule
            self._cursor = 0
            self._started_at = time.time()
            self._currently_running = None
            self._step_baselines.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def cancel(self) -> None:
        async with self._lock:
            self._schedule = None
            self._cursor = 0
            self._started_at = None
            self._currently_running = None
            self._step_baselines.clear()
        # We DON'T cancel the task itself — it'll see schedule=None on
        # its next tick and idle. Avoids the "task cancelled mid-MIDI"
        # failure mode.

    def snapshot(self) -> AgentStateSnapshot:
        """Cheap, lock-free read of the public state. Slightly racy on
        cursor / currently_running but that's a UX-level concern, not a
        correctness one — the next /agent/state poll resolves it."""
        if self._schedule is None:
            return AgentStateSnapshot(active=False, started_at_unix=None, steps=())

        # Local import to avoid a top-level cycle (services → backend.services
        # is the dependency direction we want to preserve).
        from .signatures import affects_label, summary_signature

        rows: list[_PublicStepStatus] = []
        live = self._snapshot()
        for i, step in enumerate(self._schedule.steps):
            kind, deck, at, count = _trigger_kind(step.trigger)
            if i < self._cursor:
                status = "done"
            elif i == self._currently_running:
                status = "running"
            else:
                status = "pending"

            remaining = self._remaining_beats(i, step, live) if (
                isinstance(step.trigger, AfterBeats)
                and status == "pending"
                and live is not None
            ) else None

            # Signature = the same fn-style label PlanStep renders for
            # synchronous plans. Inner-plan summary for multi-step bass
            # swaps + composite moves; single-action steps fall through
            # to render_action via summary_signature's 1-step branch.
            inner_actions = [s.action for s in step.plan.steps]
            signature = summary_signature(inner_actions) or step.label
            affects = affects_label(inner_actions)

            rows.append(
                _PublicStepStatus(
                    label=step.label,
                    trigger_kind=kind,
                    trigger_deck=deck,
                    trigger_at=at,
                    trigger_count=count,
                    remaining_count=remaining,
                    signature=signature,
                    affects=affects,
                    status=status,
                )
            )

        return AgentStateSnapshot(
            active=True,
            started_at_unix=self._started_at,
            steps=tuple(rows),
        )

    def _remaining_beats(
        self,
        cursor: int,
        step: ScheduledPlan,
        live: MixxxState,
    ) -> Optional[int]:
        """How many beats are still to come before this AfterBeats step
        fires. Used purely for UI countdown — runtime decisions go through
        Trigger.fires(). None when no baseline exists yet (step hasn't
        become current) — UI then shows the full requested count."""
        trigger = step.trigger
        if not isinstance(trigger, AfterBeats):
            return None
        baseline = self._step_baselines.get(cursor)
        if baseline is None:
            return trigger.count
        elapsed = (
            live.deck(trigger.deck).beat_count
            - baseline.deck(trigger.deck).beat_count
        )
        return max(0, trigger.count - elapsed)

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
                        self._step_baselines.clear()
                    return

                step = schedule.steps[self._cursor]
                state = self._snapshot()
                if state is None:
                    # Feedback unavailable — Mixxx probably down. Hold
                    # the schedule pending instead of erroring out; the
                    # user can cancel from the UI.
                    continue

                # First time we see this cursor → capture the baseline.
                # AfterBeats compares against it; other triggers ignore.
                baseline = self._step_baselines.get(self._cursor)
                if baseline is None:
                    baseline = state
                    self._step_baselines[self._cursor] = baseline

                if not step.trigger.fires(state, baseline):
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
