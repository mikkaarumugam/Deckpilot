# AGENT_DESIGN.md

Design notes for the agent layer — DeckPilot's biggest pending feature
("Thread 4"). This doc captures the thinking we sketched in
conversation but didn't yet implement. If you're picking this up cold,
read `docs/ARCHITECTURE.md` first.

## The framing

Today DeckPilot is a **translator** — natural language → ActionPlan →
MIDI. The user is in the loop on every action. The agent layer turns
it into a **planner** — the user states a goal, and the system plans
the sequence of actions itself.

User-flow comparison:

```
Today (translator)
  user: "bass swap into deck 2 over 4 seconds"
  system: <executes the literal 6-step bass swap immediately>

Agent layer (planner)
  user: "transition to deck 2 in the next 16 bars"
  system: <reads deck 1's BPM and position; computes when 16 bars
           will pass; schedules a bass-swap plan to fire at that
           moment; lets the user know what's queued>
```

The architectural delta is small. Three new things needed: **state
read-back, musical-time scheduling, and a planning loop**. Everything
else (parser, ActionPlan, executor, MidiAdapter, Mixxx mapping) stays.

## Why this is the bridge to "agentic AI"

The single-action AI product translates one input to one output.
The agent product takes a *goal* and plans a *sequence over time*,
with the ability to *adapt to feedback*. Examples in the wild:

- Cursor's `compose` agent — plans a multi-file edit, applies it.
- Devin — plans an entire engineering task, executes over hours.
- Claude Code itself — plans + executes against a codebase.

DeckPilot's agent layer is the same shape, smaller scale: plan over
seconds, against MIDI controls, with musical-time as the clock.

## The three new things

### 1. State read-back from Mixxx

The executor today is fire-and-forget. It doesn't know what BPM is
playing, where the playhead is, what the crossfader is at. For an
agent to plan musically-correct transitions, it needs that state.

**Options to get state:**

| Approach | Pros | Cons |
|---|---|---|
| **Mixxx MIDI output** (feedback CCs) | Native, real-time, no extra deps | Requires extending Mixxx mapping; limited control set |
| **Mixxx HTTP API** | Read any control by name | Bigger dependency; HTTP latency; not all Mixxx builds support |
| **Mixxx OSC** | Standard protocol | Setup overhead |
| **Internal model** (assume + extrapolate) | Zero dependency | Wrong as soon as user touches Mixxx UI |

Recommended: **MIDI output feedback** for the few signals we actually
need — current BPM, playing state, playhead position. Configure Mixxx
to emit these as CCs on a feedback channel; subscribe via the same
`python-rtmidi` library we already use. Same architectural pattern as
the existing send-side adapter.

New code lives in `deckpilot/adapters/midi_feedback.py` (sibling of
`midi.py`).

### 2. Musical-time scheduling

Today's `at_seconds` in `TimedAction` is wall-clock time from plan
start. That's fine for "fade over 4 seconds" but wrong for "start at
beat 16 of deck 2." DJs think in beats and bars, not seconds.

**Required:**

- An `at_beats` alternative to `at_seconds` in `TimedAction` (or a
  general `At` union type).
- The executor needs to convert `at_beats` to wall-clock time using
  the current BPM (from state read-back).
- Re-conversion needs to happen if BPM changes mid-plan.

**Design sketch:**

```python
@dataclass(frozen=True)
class At:
    """Discriminated union: at_seconds or at_beats."""
    seconds: float | None = None
    beats: float | None = None
    relative_to: Literal["plan_start", "next_downbeat", "deck1_beat", "deck2_beat"] = "plan_start"

@dataclass(frozen=True)
class TimedAction:
    action: DJAction
    at: At = At(seconds=0.0)
```

The executor resolves `At` to wall-clock at run time using current
state. "Schedule for next downbeat" becomes "compute distance to next
downbeat in seconds given BPM and playhead, schedule wall-clock."

### 3. The planning loop

Today's parser is one-shot: text → ActionPlan → done. An agent needs
to:

a. **Take a goal**, not just a command. ("transition to deck 2",
   "build energy for the next minute".)
b. **Read current state** to inform the plan.
c. **Plan an ActionPlan** — possibly with musical-time scheduling.
d. **Optionally explain** the plan ("I'll start at the next 16-beat
   downbeat, do a 4-bar bass swap, then ride deck 2 for 32 bars").
e. **Execute** through the existing executor.
f. **Optionally re-plan** if state diverges (track ends, user
   intervenes).

The planning step is another LLM call — same `claude -p`
infrastructure, different system prompt. The output schema extends
ActionPlan with `At` instead of raw `at_seconds`.

**Two implementation paths:**

- **Path A — Replan once, execute.** User states goal. LLM emits a
  full ActionPlan. Executor walks it. If state changes mid-execution,
  too bad. Simple, demo-friendly.
- **Path B — Plan, execute partially, re-plan.** Loop: LLM produces
  the next N seconds of plan; executor runs it; re-read state;
  feed back into LLM for the next N seconds. More agentic, more
  complex.

For DeckPilot's portfolio scope, **Path A** is enough. Mention Path B
as future work to demonstrate awareness of the spectrum.

## What changes in the existing code

Minimal. The architecture was designed for this.

- `core/actions.py` — add `At` discriminated union; update
  `TimedAction.at_seconds` → `TimedAction.at: At`.
- `core/executor.py` — resolve `At` to wall-clock at plan-walk time;
  query state for musical-time conversions.
- `adapters/midi_feedback.py` (new) — subscribe to Mixxx CCs for BPM,
  position, playing state. Expose a `MixxxState` snapshot dataclass.
- `core/agent.py` (new) — the planning loop; takes a goal + state,
  emits an ActionPlan.
- `core/parser/llm.py` — alternative system prompt for agent mode;
  same JSON output structure, but `at` values can reference beats /
  downbeats.

Existing parser/regex stays. Existing dashboard works unchanged. New
agent panel in the dashboard sits alongside the current "Execute"
flow, doesn't replace it.

## Open design questions

These need answering before serious implementation work:

1. **How does the user invoke agent mode vs. command mode?** Toggle?
   Different button? Implicit ("if the prompt is a goal, agent")? My
   lean: an explicit "🤖 Plan" button alongside Execute/Queue. The
   ambiguity isn't worth model-side classification.

2. **What's the minimal state we actually need?** If we only need BPM
   + playing state + crossfader position, we can ship Path A without
   the full Mixxx HTTP/OSC dance.

3. **How do we surface "I'm waiting for the next downbeat" to the
   user?** A countdown in the status panel? A live timeline view?
   Important for trust.

4. **What's the failure mode if state read-back lags or fails?**
   Default to "act now" rather than freezing? Show "waiting for
   state..."? Important for not getting stuck.

5. **How do we handle interruption?** User clicks "cancel" mid-plan
   → what happens? Stop where we are? Roll back? Execute a quick
   reset? My lean: stop immediately, expose "↶ undo the partial
   execution" if they want recovery.

## Why we parked it

The agent layer is the conceptually richest direction but the *least*
incremental — it's mostly new code, not a tweak to existing code. We
parked it because:

- The "translator" version (today's system) is already demoable as a
  complete portfolio piece.
- Implementing the agent requires state read-back, which itself
  requires Mixxx-side configuration that's harder to reproduce for
  someone trying the repo.
- The eval doc and UI redesign are higher-ROI per hour spent for the
  portfolio narrative.

When picking it back up, start with the simplest version: **a single
agent button that takes a goal string, calls the LLM with a planning
prompt, gets back an ActionPlan with `at_seconds` (no musical time
yet), and runs it through the existing executor.** That gets the
plumbing right without the BPM-tracking complexity. Add musical time
in a second pass.
