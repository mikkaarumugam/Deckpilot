# DeckPilot

**Talk to your decks.** A natural-language control layer for DJ software. You type a command — *"bass swap into deck 2 over 4 seconds"*, *"queue a daft punk track"*, *"in 16 beats, fade to deck 2"* — and DeckPilot parses it, decomposes multi-step moves into a coordinated plan, then executes it inside [Mixxx](https://mixxx.org) via virtual MIDI. The agent layer can wait on musical time and fire transitions autonomously.

Portfolio piece for AI PM applications. The interesting bits are the *architecture* (LLM emits structured actions, never raw MIDI), the *evaluation methodology* (curated suite with failure-mode taxonomy), the *scoping decisions* (23 ADR entries explaining the *why* behind every major call), and the *agent layer* (Tier-2 goal-directed scheduling + Tier-3 beat-aware triggers).

> **Status:** v0.3 — React + FastAPI frontend, agent layer with beat-aware triggers, 13 typed actions, 100 parametrized tests green. macOS-only.

---

## What it does

```
   text  ──▶  parser ──▶  ActionPlan  ──▶  executor  ──▶  MidiAdapter  ──▶  IAC  ──▶  Mixxx
          (regex|LLM)        │           (timeline)                                    ◀──┐
                             ▼                                                            │
                       AgentSchedule                                                      │
                       (trigger-gated steps)                                              │
                             │                          ┌──────────── MIDI feedback ──────┘
                             ▼                          ▼
                       AgentRuntime                Library lookup +
                       (polls state, fires)       live deck state +
                                                  beat ticks
```

**Four-tier capability stack:**

1. **Translate.** Single-shot commands → MIDI actions. *"play deck 1"* fires a play-note via the IAC virtual MIDI driver. Regex catches canonical phrasings in <1ms; the LLM (Claude Haiku via `claude -p`) handles paraphrases.

2. **Compose.** Multi-step transitions — the LLM emits coordinated plans like a 6-step bass swap (pre-cut bass, sync, fade, mid-fade swap, restore) with timed parallelism. The executor walks a flat timeline; no threading.

3. **Reason over content.** Reads Mixxx's SQLite library + listens to live deck state (play/pause, BPM, playhead position, beat ticks) over MIDI feedback. The LLM picks tracks by artist/genre/BPM/key/vibe and surfaces its choice with reasoning visible. When a pick is unambiguous, a GUI adapter loads it automatically via `osascript` driving Mixxx's library search box.

4. **Act autonomously.** Goal-style prompts (*"play X then in 16 beats bass swap into Y"*) decompose into an `AgentSchedule` — a sequence of trigger-gated plans. The runtime polls Mixxx state and fires each step when its condition hits. Two trigger types: `DeckPosition` (playhead fraction) and `AfterBeats` (musical-time counter). User does nothing for ~3 minutes; the agent does the mix.

The single interesting architectural call: **the LLM never emits raw MIDI.** It emits one of 13 typed actions; a deterministic Python layer translates each into MIDI. That gives testability, safety, and portability (the VirtualDJ → Mixxx pivot took an hour because of this). See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Demo

*(60-90s demo video TK.)*

Suggested flow:

1. `play deck 1` — regex fast-path, instant (⚡ <1ms)
2. `low pass deck 1` — filter knob sweeps in Mixxx, audible
3. `find me a chill track around 90 BPM` — suggestion card with the LLM's reasoning *("85 BPM is the lowest in the library — best fit for 'chill'")*. Auto-loads onto deck 2.
4. `bass swap into deck 2 over 4 seconds` — 6-step plan streams in one-by-one (SSE), then fires autonomously
5. `play deck 1, then in 16 beats bass swap into deck 2 over 4 seconds` — schedule preview; click Run; the agent counts down beats live and fires the swap autonomously when beat 16 hits

---

## Repo highlights

| File | What it gives you |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Entry point for any AI assistant working on this repo. ~150 lines covering conventions, file map, working style. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full pipeline explainer + action vocabulary + executor design. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 23 ADR entries — the *why* behind every architectural call. Newest first. |
| [`docs/EVAL.md`](docs/EVAL.md) | Curated parser eval with methodology, failure-mode taxonomy, latency breakdown, and "what I'd change in production." The AI PM artifact. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Shipped, next, and explicitly out of scope. |
| [`docs/GOTCHAS.md`](docs/GOTCHAS.md) | Every debugging trap I paid for, so the next person doesn't. |
| [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md) | Agent-layer design notes — musical-time planning, state-aware transitions, what's parked for v0.4. |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | Six-phase log of the React + FastAPI migration (D-018). |
| [`docs/INTERVIEW_NARRATIVE.md`](docs/INTERVIEW_NARRATIVE.md) | How I talk about DeckPilot in interviews. |

---

## Quickstart

DeckPilot targets **Mixxx** (free, open-source, MIDI-mappable). The adapter pattern means swapping in Traktor / Serato / a hardware controller is a new mapping file, not a refactor.

```bash
# 1. Clone and install
git clone <this-repo> && cd deckpilot
python -m venv .venv && source .venv/bin/activate
python -m pip install -e .

# 2. Install Mixxx
brew install --cask mixxx

# 3. Enable macOS virtual MIDI
# Open Audio MIDI Setup → Window → Show MIDI Studio → IAC Driver
# → check "Device is online" → Apply

# 4. Copy the Mixxx mapping into Mixxx's controllers folder
DEST="$HOME/Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx/controllers"
cp deckpilot/adapters/mappings/mixxx.midi.xml "$DEST/DeckPilot.midi.xml"
cp deckpilot/adapters/mappings/mixxx.midi.js  "$DEST/DeckPilot.midi.js"

# 5. Launch Mixxx, then: Preferences → Controllers → IAC Driver Bus 1
#    → load "DeckPilot" → check "Enabled" → Apply
# Load a couple of tracks onto deck 1 and deck 2.

# 6. Verify Python can talk to MIDI
python scripts/send_test_note.py
# (with deck 1 paused, this starts playback)

# 7. Run a command via the CLI
python -m deckpilot "play deck 1"
python -m deckpilot "bass swap into deck 2 over 4 seconds"
```

**Or run the React + FastAPI dashboard** (the polished version with live state, suggestion cards, and the agent queue):

```bash
# Backend
uvicorn backend.main:app --port 8000 --reload

# Frontend (in another terminal)
cd frontend && npm install && npm run dev
# Open http://localhost:5173
```

> **Heads-up — only one Python process can hold the IAC port at a time.** Kill Streamlit before starting uvicorn (and vice versa): `pkill -f "streamlit run"`. See [`docs/GOTCHAS.md`](docs/GOTCHAS.md) for the full list of setup pitfalls.

The Streamlit dashboard from earlier versions (`app/dashboard.py`) still works as a fallback; the React frontend is the demo-facing one.

The LLM parser shells out to the `claude -p` CLI (uses your existing Claude Pro subscription, no metered API key). Install Claude Code from <https://claude.com/claude-code> if you don't have it. See [D-007](docs/DECISIONS.md) for the rationale; the Anthropic SDK swap path is documented as ~30 lines in `parser/llm.py`.

---

## Supported actions (v0.3)

Thirteen typed actions, all atomic except `FadeToDeck` which the executor expands into a stream of `SetCrossfader` events:

| Action          | Example phrase                                                |
|-----------------|---------------------------------------------------------------|
| `play_deck`     | *"play deck 1"*, *"drop deck 2"*, *"kick in"*                 |
| `pause_deck`    | *"pause deck 2"*, *"halt"*                                    |
| `set_crossfader`| *"crossfader to the middle"*                                  |
| `fade_to_deck`  | *"fade to deck 2 over 8 seconds"*                             |
| `loop_deck`     | *"loop deck 1 for 4 beats"*, *"loop 32 beats"*, *"kill loop"* |
| `nudge_deck`    | *"nudge deck 2 forward"*                                      |
| `set_eq`        | *"kill the bass on deck 1"*, *"bring back the highs"*         |
| `set_volume`    | *"deck 2 volume to 80%"*                                      |
| `set_filter`    | *"low pass deck 1"*, *"high pass deck 2"*, *"filter off"*     |
| `set_fx`        | *"fx 1 to 50% on deck 1"*, *"kill fx 2"*                      |
| `set_pitch`     | *"pitch deck 1 up 4%"*, *"reset pitch"*                       |
| `hot_cue`       | *"jump to cue 3 on deck 1"*                                   |
| `sync`          | *"sync deck 2"*                                               |
| `load_track`    | *"queue a daft punk track"* — surfaced as a suggestion card (see [D-015](docs/DECISIONS.md) / [D-019](docs/DECISIONS.md)) |

Multi-step transitions are composed by the LLM, not hardcoded: *"bass swap into deck 2 over 4 seconds"* emits a 6-step plan with parallel timing (pre-cut bass + sync + fade + mid-fade swap + restore).

### Agent schedules (D-021 + D-023)

Goal-style prompts produce an `AgentSchedule` — a sequence of plans gated by triggers:

| Trigger          | Example phrase                                                      |
|------------------|---------------------------------------------------------------------|
| `Immediate`      | *"... then ..."* — fires at schedule start                          |
| `DeckPosition`   | *"... when deck 1 is near end ..."* — fires when playhead ≥ fraction|
| `AfterBeats`     | *"... in 16 beats ..."* — fires after N beats counted on a deck     |

The `AgentRuntime` polls Mixxx state at 500ms and fires each plan when its trigger condition hits. The user sees a live countdown in the queue panel. See [D-021](docs/DECISIONS.md) (Tier-2: position triggers) and [D-023](docs/DECISIONS.md) (Tier-3: beat-aware triggers).

---

## Architecture, in one diagram

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the long version. Headlines:

- **Structured action vocabulary** — LLM emits one of 13 typed dataclasses, never raw MIDI.
- **Two-tier parser** — regex first (free, <1ms, deterministic), Claude Haiku second (paraphrases + composition + library-aware track picks).
- **Plan-as-timeline** — multi-step transitions are first-class. The executor flattens any `FadeToDeck` into ~120 atomic `SetCrossfader` events, sorts the timeline, walks it.
- **Adapter pattern is sacred** — the `MidiAdapter` dispatches one MIDI message per atomic action. Swapping DJ software is writing a new adapter.
- **MIDI feedback** — Mixxx → Python over the same IAC bus. Play state, BPM, playhead position, active loop size, and beat ticks — all read back so the agent can reason over real state, not assumptions.
- **GUI adapter for what MIDI can't reach** — Mixxx's controller-script API has no path-based track-load primitive across versions 2.5-2.7, so the `MixxxGuiAdapter` drives Mixxx's library search box via `osascript` when a track pick is unambiguous (D-019). Falls back to a manual-drag suggestion card otherwise.
- **Streaming LLM parses** — the backend streams plan steps via SSE as Haiku generates them; the React UI populates the plan one row at a time (D-020).
- **Agent layer** — `AgentSchedule` is a peer abstraction to `ActionPlan`; the same atomic-action vocabulary, wrapped in a trigger-gated envelope (D-021/D-023).

---

## Evaluation

[`docs/EVAL.md`](docs/EVAL.md) — curated suite with full methodology, failure-mode taxonomy, latency breakdown (where the LLM p50 actually goes), and a "what I'd change in production" section.

The eval covers the parser core. The newer agent layer (D-021/D-023) is exercised via unit tests in [`tests/test_agent.py`](tests/test_agent.py) (Trigger semantics, AgentRuntime baseline behavior, LLM validator round-trips).

The accuracy number is not the AI PM signal. The methodology is. Every claim is falsifiable; every limitation is acknowledged; every "we'd fix this" sentence is concrete.

---

## What I'd build next

In rough priority order (see [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full list):

1. **Recovery + re-planning in the agent** — if the schedule's assumptions go wrong (track ran out early, BPM drifted), today the user cancels + re-prompts. A self-correcting scheduler is the Tier-4 piece.
2. **Multi-schedule queue / stacked goals** — currently one active schedule at a time. The UX shape for chaining is partly there (the Queue button) but stacked schedules aren't.
3. **Anthropic SDK + prompt caching** — drops LLM latency ~40%, input cost ~90%. ~30-line swap in `parser/llm.py`. Trade-off: adds metered cost (D-007).
4. **Adversarial eval extension** — prompt-injection cases, slang, out-of-range values, cross-run variance.
5. **MCP server** — let Claude Desktop / Cursor drive DeckPilot directly.

---

## Repo layout

```
deckpilot/                  importable package
  core/
    actions.py              DJAction schema + ActionPlan + TimedAction
    agent.py                Trigger union + AgentSchedule (D-021/D-023)
    executor.py             walks the plan, expands FadeToDeck, dispatches
    undo.py                 inverse_action / inverse_plan / reset_plan
    parser/
      __init__.py           facade: regex first, fall back to LLM
      regex.py              ~24 patterns for canonical phrasings + state-aware stop-loop
      llm.py                claude -p subprocess + JSON validation
  adapters/
    base.py                 Adapter interface
    midi.py                 MidiAdapter (python-rtmidi → IAC)
    midi_feedback.py        MixxxFeedback (Mixxx → Python state read-back)
    gui.py                  MixxxGuiAdapter (osascript-driven GUI; D-019)
    mappings/
      mixxx.midi.xml        Mixxx-side bindings (notes/CCs ↔ controls)
      mixxx.midi.js         JS handlers for play/pause, BPM, position, beat-ticks, loop-size
  library/
    reader.py               read-only Mixxx SQLite library reader
  __main__.py               CLI entry

backend/                    FastAPI HTTP wrapper (D-018)
  main.py                   app + CORS + lifespan + routes
  models.py                 Pydantic wire schemas
  routes/                   /parse, /execute, /state, /undo, /reset, /agent/*
  services/
    singletons.py           lazy adapters / executor / feedback (fail-soft)
    agent_runtime.py        AgentRuntime: polls state, fires trigger-gated plans
    signatures.py           DJAction → display strings for the UI

frontend/                   Vite + React + TS (D-018)
  src/
    Pilot.tsx               app shell
    hooks/usePilotFlow.ts   Pattern C state machine + command queue
    hooks/useAgentState.ts  polls /agent/state
    hooks/useDeckState.ts   polls /state at 250ms
    components/
      CommandCard.tsx       hero card: input + parsed pill + plan/schedule preview
      PlanStep.tsx          rail+node timeline row
      AgentQueue.tsx        live agent panel with beat countdown
      Signature.tsx         syntax-highlighted fn signature rendering
      DeckCard.tsx          live deck panel with BPM + artwork + track meta

app/dashboard.py            Streamlit frontend (the original; still works)
scripts/send_test_note.py   MIDI sanity test
tests/test_parser.py        77 parametrized regex tests
tests/test_agent.py         23 parametrized agent-layer tests
tests/eval.py               eval harness for docs/EVAL.md
docs/                       ARCHITECTURE, DECISIONS, ROADMAP, GOTCHAS, EVAL, MIGRATION, AGENT_DESIGN, INTERVIEW_NARRATIVE
```

---

## Why this project exists

To prove I can ship an end-to-end AI product, not just talk about one. AI PM portfolios are usually RAG chatbots; I wanted something with real-time constraints (audio, latency, hardware integration) and a non-trivial agent layer. The intersection of LLMs and a real-time creative tool seemed underexplored.

See [`docs/INTERVIEW_NARRATIVE.md`](docs/INTERVIEW_NARRATIVE.md) for how I talk about it.
