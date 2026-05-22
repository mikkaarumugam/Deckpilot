# DeckPilot

**Talk to your decks.** A natural-language control layer for DJ software. You type a command — *"bass swap into deck 2 over 4 seconds"*, *"queue a daft punk track"*, *"kill the bass on deck 1"* — and DeckPilot parses it into a structured multi-step plan, then executes it inside [Mixxx](https://mixxx.org) via virtual MIDI.

Portfolio piece for AI PM applications. The interesting bits are the *architecture* (LLM emits structured actions, not raw MIDI), the *evaluation methodology* (29-case eval with failure-mode taxonomy), and the *scoping decisions* (14 ADR entries explaining the *why* behind every major call).

> **Status:** library-aware, ~21 commits on `main`, eval at 29/29 on the curated suite. Demo video pending.

---

## What it does

```
   text  ──▶  parser ──▶ ActionPlan ──▶  executor  ──▶  MidiAdapter  ──▶  IAC  ──▶  Mixxx
          (regex|LLM)                  (timeline)                                    ◀──┐
                                                                                        │
                                              ┌──────────── MIDI feedback ──────────────┘
                                              ▼
                                       Library lookup +
                                       live deck state
```

**Three-tier capability stack:**

1. **Translate.** Single-shot commands → MIDI actions. *"play deck 1"* fires a play-note via the IAC virtual MIDI driver. Regex catches canonical phrasings in <1ms; the LLM (Claude Haiku via `claude -p`) handles paraphrases.

2. **Compose.** Multi-step transitions — the LLM emits coordinated plans like a 6-step bass swap (pre-cut bass, sync, fade, mid-fade swap, restore) with timed parallelism. The executor walks a flat timeline; no threading.

3. **Reason over content.** Reads Mixxx's SQLite library + listens to live deck state (play/pause + canonical BPM) over MIDI feedback. The LLM picks tracks by artist/genre/BPM/key/vibe and surfaces its choice as a suggestion card.

The single interesting architectural call: **the LLM never emits raw MIDI.** It emits one of ten typed actions; a deterministic Python layer translates each into MIDI. That gives testability, safety, and portability (the VirtualDJ → Mixxx pivot took an hour because of this). See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Demo

*(60-90s demo video TK.)*

Suggested flow:

1. `play deck 1` — regex fast-path, instant (⚡ 0.00s)
2. `kill the bass on deck 1` — same path, more interesting verbs
3. `find me something around 90 BPM` — surfaces a "🎵 AI suggests for deck 2" card with library-grounded reasoning
4. *(drag the suggested track onto deck 2)*
5. `bass swap into deck 2 over 4 seconds` — multi-step plan renders before audio fires; 6 steps execute autonomously

---

## Repo highlights

| File | What it gives you |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Entry point for any AI assistant working on this repo. ~100 lines covering conventions, file map, working style. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full pipeline explainer + action vocabulary + executor design. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 17 ADR entries — the *why* behind every architectural call. |
| [`docs/EVAL.md`](docs/EVAL.md) | 29-case eval with methodology, failure-mode taxonomy, and "what I'd change in production." The AI PM artifact. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Shipped, next, and explicitly out of scope. |
| [`docs/GOTCHAS.md`](docs/GOTCHAS.md) | Every debugging trap I paid for, so the next person doesn't. |
| [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md) | Parked: design notes for the agent layer (musical-time planning, state-aware transitions). |
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

# 8. Or run the dashboard
streamlit run app/dashboard.py
```

The LLM parser shells out to the `claude -p` CLI (uses your existing Claude Pro subscription, no metered API key). Install Claude Code from <https://claude.com/claude-code> if you don't have it.

---

## Supported actions (v0.3)

Ten typed actions, all atomic except `FadeToDeck` which the executor expands:

| Action          | Example phrase                                 |
|-----------------|------------------------------------------------|
| `play_deck`     | *"play deck 1"*, *"drop deck 2"*, *"kick in"*  |
| `pause_deck`    | *"pause deck 2"*, *"halt"*                     |
| `set_crossfader`| *"crossfader to the middle"*                   |
| `fade_to_deck`  | *"fade to deck 2 over 8 seconds"*              |
| `loop_deck`     | *"loop deck 1 for 8 beats"*, *"kill loop"*     |
| `nudge_deck`    | *"nudge deck 2 forward"*                       |
| `set_eq`        | *"kill the bass on deck 1"*, *"bring back the highs"* |
| `set_volume`    | *"deck 2 volume to 80%"*                       |
| `hot_cue`       | *"jump to cue 3 on deck 1"*                    |
| `sync`          | *"sync deck 2"*                                |
| `load_track`    | *"queue a daft punk track"* — surfaced as a suggestion (see [D-015](docs/DECISIONS.md)) |

Multi-step transitions are composed by the LLM, not hardcoded: *"bass swap into deck 2 over 4 seconds"* emits a 6-step plan with parallel timing (pre-cut bass + sync + fade + mid-fade swap + restore).

---

## Architecture, in one diagram

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the long version. Headlines:

- **Structured action vocabulary** — LLM emits one of 10 typed dataclasses, never raw MIDI.
- **Two-tier parser** — regex first (free, <1ms, deterministic), Claude Haiku second (paraphrases + composition).
- **Plan-as-timeline** — multi-step transitions are first-class. The executor flattens any `FadeToDeck` into ~120 atomic `SetCrossfader` events, sorts the timeline, walks it.
- **Adapter pattern is sacred** — the MidiAdapter dispatches one MIDI message per atomic action. Swapping DJ software is writing a new adapter.
- **MIDI feedback** — Mixxx → Python over the same IAC bus. Play state via `<output>` bindings; canonical BPM via scripted JS using `engine.makeConnection`.
- **Library awareness via SQLite + LLM context** — read-only access to Mixxx's library DB, embedded in the LLM prompt at parse time so the model can pick tracks by criteria.

---

## Evaluation

[`docs/EVAL.md`](docs/EVAL.md) — 29-case curated suite, 100% pass, with full methodology, failure-mode taxonomy, latency breakdown (where the ~4s LLM p50 actually goes), and a "what I'd change in production" section.

That doc — not the 100% number itself — is the AI PM signal. Every claim is falsifiable; every limitation is acknowledged; every "we'd fix this" sentence is concrete.

---

## What I'd build next

In rough priority order (see [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full list):

1. **Agent layer** (`docs/AGENT_DESIGN.md`) — musical-time scheduling, goal-directed planning ("transition to deck 2 in 16 bars"). Now substrate-ready thanks to state read-back.
2. **Anthropic SDK + prompt caching** — drops LLM latency ~40%, input cost ~90%. ~30-line swap in `parser/llm.py`.
3. **Adversarial eval** — prompt-injection cases, slang, out-of-range values, cross-run variance.
4. **MCP server** — let Claude Desktop / Cursor drive DeckPilot directly.

---

## Repo layout

```
deckpilot/                  importable package
  core/
    actions.py              DJAction schema + ActionPlan + TimedAction
    executor.py             walks the plan, expands FadeToDeck, dispatches
    undo.py                 inverse_action / inverse_plan / reset_plan
    parser/
      __init__.py           facade: regex first, fall back to LLM
      regex.py              ~12 patterns for canonical phrasings
      llm.py                claude -p subprocess + JSON validation
  adapters/
    base.py                 Adapter interface
    midi.py                 MidiAdapter (python-rtmidi → IAC)
    midi_feedback.py        MixxxFeedback (Mixxx → Python state read-back)
    mappings/
      mixxx.midi.xml        Mixxx-side bindings (notes/CCs ↔ controls)
      mixxx.midi.js         JS handlers for play/pause + BPM output
  library/
    reader.py               read-only Mixxx SQLite library reader
  __main__.py               CLI entry

app/dashboard.py            Streamlit frontend
scripts/send_test_note.py   MIDI sanity test
tests/test_parser.py        47 parametrized regex tests
tests/eval.py               eval harness for docs/EVAL.md
docs/                       ARCHITECTURE, DECISIONS, ROADMAP, GOTCHAS, EVAL, …
```

---

## Why this project exists

To prove I can ship an end-to-end AI product, not just talk about one. AI PM portfolios are usually RAG chatbots; I wanted something with real-time constraints (audio, latency, hardware integration). The intersection of LLMs and a real-time creative tool seemed underexplored.

See [`docs/INTERVIEW_NARRATIVE.md`](docs/INTERVIEW_NARRATIVE.md) for how I talk about it.
