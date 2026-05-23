# Architecture

## The pipeline

```
   text  ──▶  parser ──▶ ActionPlan ──▶ executor ──▶ MidiAdapter ──▶ IAC ──▶ Mixxx
          (regex|LLM)                 (timeline)    (note/CC table)

                                            │
                                            ▼
                                       Mixxx XML maps
                                        notes/CC →
                                       Mixxx controls
```

Six moving parts:

1. **Text input** — CLI argument, dashboard text box, or WhisperType
   dictation. Becomes a single string.
2. **Parser** — turns the string into an `ActionPlan` (one or more
   timed atomic actions). Two backends: regex (fast, deterministic) and
   LLM (paraphrase + multi-step composition).
3. **ActionPlan** — `tuple[TimedAction]` where each TimedAction wraps
   a DJAction with an `at_seconds` offset from plan start.
4. **Executor** — walks the plan. Expands composite actions
   (FadeToDeck → series of SetCrossfader CCs). Sorts the resulting
   timeline by time and dispatches each atomic action at its scheduled
   moment via `time.sleep`.
5. **MidiAdapter** — turns atomic actions into MIDI messages and
   ships them through the IAC Driver port. Each atomic action type
   maps to a fixed note or CC, defined in `midi.py` constants.
6. **Mixxx XML mapping** — Mixxx loads this from its controllers
   folder. Maps incoming MIDI (status + note/CC number) to Mixxx
   controls (`engine.setValue` calls).

## Why this shape

### Structured intent, not raw control

We *deliberately* don't let the LLM emit raw MIDI. It emits one of N
typed actions; the deterministic Python layer translates an action to
MIDI. This gives us:

- **Testability** — the parser can be unit-tested without Mixxx running.
- **Safety** — the LLM can't ask for something we don't support; the
  validator in `llm.py:_payload_to_action` rejects out-of-vocabulary
  shapes.
- **Portability** — swapping DJ software = new adapter mapping, nothing
  else changes. We validated this once (VirtualDJ → Mixxx pivot in an
  hour).

### Two-tier parsing

Regex catches the head of the distribution (predictable phrasings),
LLM catches the tail (paraphrases + composition). Trade-off summary:

| | Regex | LLM (Haiku via claude -p) |
|---|---|---|
| Latency | <1ms | ~700-1500ms |
| Cost | Free | Free (subscription); metered if SDK |
| Determinism | 100% | Probabilistic |
| Coverage | Whatever rules you wrote | Everything the model understands |
| Composition | Single action only | Multi-step plans |

When in doubt: **add a regex rule** for new common phrasings rather
than upgrading the LLM. See D-005 / `b39d6d6`.

### Plan-as-timeline (not as a sequence)

Multi-step actions like "bass swap" have parallel timing — a fade can
overlap with an EQ cut at the fade midpoint. The executor handles this
by expanding all composite steps into atomic events first, sorting by
time, then walking the flat timeline. **No threading.** Single-threaded
deterministic walk, easy to reason about.

This is also the substrate for the future agent layer: anything that
emits an ActionPlan goes through the same executor.

## The action vocabulary (10 atomic types)

Defined in `core/actions.py`. Each is a frozen dataclass.

| Action | Fields | What it does |
|---|---|---|
| `PlayDeck` | `deck: int` | Start playback on deck N |
| `PauseDeck` | `deck: int` | Pause deck N |
| `SetCrossfader` | `value: float 0..1` | Absolute crossfader position |
| `FadeToDeck` | `deck: int, seconds: float` | Composite: interpolated crossfader |
| `LoopDeck` | `deck: int, beats: int` | Toggle an 8-beat loop (beats currently ignored in mapping) |
| `NudgeDeck` | `deck: int, direction: 'forward'\|'back'` | Tap nudge-rate button |
| `SetEQ` | `deck: int, band: 'low'\|'mid'\|'high', value: float 0..1` | Set one EQ band |
| `SetVolume` | `deck: int, value: float 0..1` | Channel fader |
| `HotCue` | `deck: int, cue: int 1..8` | Jump to (or set) a hot cue |
| `Sync` | `deck: int` | Mixxx beatsync trigger |

`FadeToDeck` is the only composite. Everything else is atomic.

## The plan layer

```python
@dataclass(frozen=True)
class TimedAction:
    action: DJAction         # any atomic OR FadeToDeck
    at_seconds: float = 0.0  # absolute time from plan start

@dataclass(frozen=True)
class ActionPlan:
    steps: tuple[TimedAction, ...]
```

The parser always returns an `ActionPlan`. Single-action commands get
wrapped via `ActionPlan.single(action)`. Multi-step plans like bass
swap have multiple TimedActions with different `at_seconds`.

## The executor walk

```python
def run_plan(self, plan):
    timeline = self._expand(plan)        # FadeToDeck → SetCrossfader stream
    start = time.monotonic()
    for event in timeline:               # sorted by at_seconds
        wait = (start + event.at_seconds) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._adapter.dispatch(event.action)
```

The expansion for a 4-second FadeToDeck at `at_seconds=0` produces ~120
SetCrossfader events at 30 fps, each with its own `at_seconds` offset.
A SetEQ scheduled at `at_seconds=2` lands cleanly in the middle of the
expanded fade stream — no threading, no coordination.

## MIDI side

`MidiAdapter.dispatch(action)` translates one atomic action to one or
two MIDI messages. The note/CC numbers are module-level constants in
`midi.py` and MUST match `adapters/mappings/mixxx.midi.xml`.

Most actions = one note_on with velocity 127. Exceptions:

- `SetCrossfader`, `SetEQ`, `SetVolume` → CC with value (CC controller
  + scaled 0-127 value).
- `NudgeDeck` → note_on, 100ms sleep, note_off. (Mixxx's
  `rate_temp_up/down` is a hold-to-nudge button.)
- `PauseDeck` uses a DIFFERENT NOTE from `PlayDeck` (61 vs 60) routed
  through JS script bindings in Mixxx (see D-004 / GOTCHAS § velocity
  zero).

## Mixxx-side mapping

`mixxx.midi.xml` is loaded by Mixxx and tells it what to do when MIDI
arrives. Two binding modes used:

- `<normal/>` — Mixxx scales 0..127 to control value 0..1. Used for
  CCs (crossfader, EQ, volume) and one-shot note triggers (loops, hot
  cues, sync, nudge).
- `<script-binding/>` — Calls a JS handler in `mixxx.midi.js`. Used
  for play/pause (the velocity-zero gotcha).

## Frontend layers

Two interfaces share the parser + executor:

- **CLI** (`deckpilot/__main__.py`) — argparse subcommands for
  explicit mode, plus a single-string NL form. Single-shot — opens
  MIDI port, executes, closes.
- **Dashboard** (`app/dashboard.py`) — Streamlit. Long-lived; caches
  the `MidiAdapter` in `st.session_state`. Adds: plan visualization,
  history with undo, queue, clear history, reset Mixxx.

Both go through the same parser facade and executor, so they always
behave the same with respect to action semantics.

## Library awareness (Session 3)

The LLM parser optionally receives runtime context — a snapshot of
the Mixxx library and the current deck state — at parse time. With
that context, it can pick tracks by criteria ("queue a daft punk
track", "find something around 90 BPM") and reason about which deck
to use (the one that isn't playing).

```
deckpilot/library/reader.py
  LibraryReader        — read-only SQLite access to Mixxx's library DB.
                         Opens with mode=ro (never immutable=1, so we see
                         Mixxx's writes). Joins library + track_locations
                         to expose file paths.
  Track                — frozen dataclass: id, artist, title, album,
                         genre, bpm, key, duration, location.
```

The library snapshot is rendered into the LLM's system prompt by
`build_system_prompt(library, deck_state)` — one compact line per
track. The model emits a new `load_track` action carrying a library
row id; the deterministic Python layer either dispatches it (future)
or surfaces it as a SUGGESTION (today — see D-015).

## State read-back (Session 2)

Mixxx → Python over the same IAC bus we use for sending. Two channels:

- **Play state.** Standard `<output>` mapping fires when
  `[ChannelN].play` crosses 0.5; sends note 0x10/0x11.
- **Canonical BPM.** Scripted JS subscribes to `[ChannelN].file_bpm`
  via `engine.makeConnection`, scales to a CC value (60–200 BPM →
  0–127), sends on CC 0x30/0x31. `file_bpm` (not the playback-drift
  `bpm`) is the canonical BPM that matches the library DB — see D-017.

```
deckpilot/adapters/midi_feedback.py
  MixxxFeedback        — opens IAC Bus 1 as MIDI INPUT, parses notes
                         and CCs on rtmidi's callback thread, maintains
                         a thread-safe state dict per deck.
  MixxxState/DeckState — frozen snapshot dataclasses returned from
                         snapshot().
```

A request-state handshake (note 0x7F) fires once at MixxxFeedback
startup so the sidebar gets initial state instead of waiting for
the next change.

## Frontend / Backend split (Session 6, shipped 2026-05-23)

The original Streamlit dashboard was supplemented by a React + FastAPI
stack — see DECISIONS § D-018 for the rationale. The Python brain
(`deckpilot/`) is unchanged; the new layers wrap it.

```
       ┌─────────────────────────────────────────────┐
       │  frontend/  (Vite + React + TS, port 5173)  │
       │  - Pilot.tsx                                │
       │  - usePilotFlow (Pattern C state machine)   │
       │  - useDeckState (polls /state @ 250ms)      │
       └────────────────────┬────────────────────────┘
                            │  HTTP (CORS-allowed)
                            ▼
       ┌─────────────────────────────────────────────┐
       │  backend/  (FastAPI, port 8000)             │
       │  - /parse  → core.parser.parse              │
       │  - /execute → core.executor.run_plan        │
       │  - /state  → adapters.midi_feedback         │
       │  - /undo   → core.undo.inverse_plan         │
       │  - /reset  → core.undo.reset_plan           │
       └────────────────────┬────────────────────────┘
                            │ imports
                            ▼
       ┌─────────────────────────────────────────────┐
       │  deckpilot/  (Python brain — unchanged)     │
       │  - core/parser, core/executor, core/undo    │
       │  - adapters/midi, adapters/midi_feedback    │
       │  - library/reader                           │
       └─────────────────────────────────────────────┘
```

**Pattern C** (the parse-flow design — D-018a):

- Each keystroke in the React input fires a debounced `api.parse(text,
  "regex")`. Regex is in-process + free + instant, so eager.
- If regex matches → plan renders immediately (`phase = "ready"`).
- If regex doesn't match → UI shows `(press ⏎ to ask Haiku)` hint
  but no LLM call happens yet.
- User presses Enter on a no-match → `api.parse(text, "auto")` fires
  the LLM (`phase = "parsing"` → ~3-12s wait).
- Enter on a ready plan → `api.execute(plan)` runs it.

This matches Cursor's compose pattern (Cmd+Enter for AI) and avoids
the wasted LLM calls of eager-parse approaches.

**MIDI port conflict.** Only one Python process can hold the IAC
output port at a time. Streamlit (`app/dashboard.py`) and FastAPI
(`backend.main`) compete for it — quit one before running the other.
The Streamlit dashboard stays in the repo as a working fallback.

## Future: agent layer (parked)

The architecture is designed to receive an agentic upgrade without a
refactor. An agent would:

1. Read Mixxx state (BPM, deck positions, currently playing) via MIDI
   feedback or HTTP API.
2. Plan multi-step transitions in musical time ("at the next 16-beat
   downbeat, start a 4-beat fade").
3. Emit an `ActionPlan` — same dataclass we use today.
4. The executor runs it the same way.

The only new code is the planning agent itself + a state-read-back
module. Everything else stays.
