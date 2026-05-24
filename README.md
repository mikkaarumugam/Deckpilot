# DeckPilot

**Talk to your decks.** Type a high-level DJ command — *"bass swap into deck 2 over 4 seconds"*, *"echo deck 1 out into deck 2"*, *"in 16 beats filter sweep back to deck 1"* — and an AI parses it, plans a multi-step musical move, and executes it inside [Mixxx](https://mixxx.org) via virtual MIDI. The agent layer can wait on musical time and fire transitions autonomously.

---

## What this project actually is

> I'm applying for AI product roles. I don't write code. I prompt, scope, evaluate, and direct. **DeckPilot is the artifact of that loop applied to a real-time AI product over one weekend.**

Every line of Python and TypeScript in this repo was written by Claude. Every decision about *what* to build, *why*, and *what to ship vs cut* was mine. Twenty-three [architecture decision records](docs/DECISIONS.md) document the calls I made. A [45-case eval](docs/EVAL.md) documents how I measure whether it works. A [failure-mode roadmap](docs/ROADMAP.md) documents what I deliberately didn't build and why.

If you're hiring an AI PM, this is what the day-to-day looks like — directing an AI to build a non-trivial product, owning every product decision, measuring rigorously, and shipping. The code is the proof that the process works.

---

## Demo

https://github.com/user-attachments/assets/4dcd1f69-4b4d-43d0-94e9-b86f40e5d8dc

*Fallback: [download `docs/demo.mp4`](docs/demo.mp4) if the embed doesn't play.*

Two Daft Punk tracks. Five commands. One AI doing the mixing.

1. `play deck 1` — *Around The World* drops. Regex fast-path, instant.
2. `loop deck 1 over 8 beats` — loop holds the chorus, builds tension.
3. `exit loop` — release.
4. `echo deck 1 out into deck 2 over 8 seconds` — *Around The World* trails into FX wet as *One More Time* fades in. The AI picks an FX-led transition because of the verb "echo," not a generic crossfade.
5. `in 16 beats filter sweep back to deck 1` — agent schedule. DeckPilot counts beats off *One More Time* and autonomously sweeps the filter back on beat 16. I do nothing for ~7 seconds; it runs the mix.

---

## What this proves about me as an AI PM

**1. I can scope ruthlessly.** I cut stems isolation, multi-tenant deployment, voice integration, hardware controller support, and three other features that didn't survive the weekend budget. [`docs/ROADMAP.md`](docs/ROADMAP.md) lists what's in, what's deferred, and what I explicitly won't build.

**2. I think in failure modes, not happy paths.** The eval doc has a [failure-mode taxonomy](docs/EVAL.md). The undo system, the plan-visible-before-audible UX, and the "no confirmation" decision are all designed around bounded cost-of-error — not preventing errors that can't be prevented.

**3. I pivot fast when the architecture supports it.** First target was VirtualDJ. After ~30 min I discovered VDJ Home throttles unrecognized MIDI controllers to 10 minutes per launch — actions silently no-op past that. Pivoted to Mixxx in under an hour because the adapter pattern was already drawn ([D-002](docs/DECISIONS.md)). Same weekend: pivoted from Anthropic SDK to `claude -p` CLI to avoid metered API costs ([D-007](docs/DECISIONS.md)). Both swaps shipped because the boundaries were right.

**4. I treat the prompt as the product.** The LLM picks *bass swap* vs *filter sweep* vs *echo out* vs *drop swap* based on the verb in your command — not because of model capability, but because I gave it four distinct few-shot examples keyed to four distinct verbs. One prompt edit unlocks four genuinely different musical behaviours. This is the lever that matters in production AI products, and most demos never touch it.

**5. I measure trust quantitatively.** Most "AI controls X" demos ship without ever measuring whether the AI gets it right. [`docs/EVAL.md`](docs/EVAL.md) is a 45-case suite with methodology, latency p50/p95 breakdown, source-split (regex vs LLM), and a "what I'd change in production" section. The accuracy number isn't the AI PM signal — the **methodology is**.

**6. I know when to *not* ask.** Real-time creative tools die under confirmation dialogs. I replaced "ask permission" with three things together: parsed plan renders *before* audio fires (eyes confirm before ears), one-click undo on everything reversible (bounded cost-of-error), and the eval suite (earned right to act). [Explained in detail here](docs/DECISIONS.md#d-008--no-confirmation-dialogs).

---

## What I directed vs what Claude wrote

| I did | Claude did |
|---|---|
| Scoped the product to "natural language → MIDI → Mixxx" and cut everything else | Wrote ~3,000 lines of Python + TypeScript |
| Decided on the structured action vocabulary (LLM emits typed actions, never raw MIDI) | Implemented the action dataclasses, executor, adapter, parser |
| Chose Mixxx over VDJ after the 10-min throttle bug | Wrote the Mixxx MIDI mapping XML + JS scripts |
| Designed the four-tier capability stack (translate → compose → reason → autonomous) | Built each tier when I asked |
| Wrote every system prompt — the four transition style few-shots, the deck-default rule, the JSON validator schema | Tested the prompts, surfaced failures, suggested fixes |
| Authored the 45-case eval methodology and what counts as "correct" | Wrote the eval harness |
| Made every architecture-decision call documented in [`docs/DECISIONS.md`](docs/DECISIONS.md) | Captured the why-not-what in writing |
| Picked Haiku over Sonnet/Opus and articulated when to upgrade | Wired the model selector |
| Designed the demo flow shown above (track pairing, transition arc, voiceover beats) | None — the demo is mine |

**The product is what I shipped. The skill being demonstrated is the loop.**

---

## Architecture (one diagram)

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

**Four tiers of capability**, each a separate product decision:

1. **Translate** — single commands → MIDI. Regex catches canonical phrasings in <1ms; LLM (Claude Haiku via `claude -p`) handles paraphrases. I [evaluated both](docs/EVAL.md) to decide where the boundary sits.
2. **Compose** — multi-step transitions like a 6-step bass swap, planned by the LLM, executed on a timeline.
3. **Reason over content** — reads Mixxx's SQLite library + live deck state (BPM, playhead, beat ticks) over MIDI feedback. The LLM picks tracks by artist/genre/BPM/key/vibe and shows its reasoning.
4. **Act autonomously** — goal-style prompts (*"play X then in 16 beats bass swap into Y"*) decompose into an `AgentSchedule` — trigger-gated steps that fire on musical time. User does nothing for ~3 minutes; the agent does the mix.

The one architectural call worth flagging: **the LLM never emits raw MIDI.** It emits one of 13 typed actions; a deterministic Python layer translates each into MIDI. That gives testability, safety, and portability — the VirtualDJ → Mixxx pivot took an hour because of this. Full explanation in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## The docs are the product

These are the artifacts a hiring manager should actually open:

| File | What it shows |
|---|---|
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | **23 architecture decision records.** Every major call (action vocabulary, prompt design, no-confirmation UX, model selection, agent triggers) with context, alternatives considered, and trade-offs. Newest first. This is the PM thinking artifact. |
| [`docs/EVAL.md`](docs/EVAL.md) | **45-case parser eval** with methodology, failure-mode taxonomy, latency p50/p95, source split (regex vs LLM), and "what I'd change in production." Trust-via-measurement. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Shipped milestones, next priorities, and explicitly-out-of-scope items. Scoping discipline made visible. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline explainer, action vocabulary, executor design. |
| [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md) | Why musical-time triggers exist, the state-in-runtime vs state-in-trigger debate, what's parked for v0.4. |
| [`docs/GOTCHAS.md`](docs/GOTCHAS.md) | Every debugging trap I paid for. The honest version of what shipping involved. |
| [`docs/INTERVIEW_NARRATIVE.md`](docs/INTERVIEW_NARRATIVE.md) | How I tell this story in interviews — 60-second pitch, key Q&A, the senior-PM lines worth memorizing. |
| [`CLAUDE.md`](CLAUDE.md) | What I tell Claude at the start of every session in this repo. The "system prompt" for my engineering loop. |

---

## Try it yourself

DeckPilot targets **Mixxx** (free, open-source, MIDI-mappable) on macOS.

```bash
# Clone and install
git clone https://github.com/mikkaarumugam/Deckpilot.git && cd Deckpilot
python -m venv .venv && source .venv/bin/activate
python -m pip install -e .

# Install Mixxx
brew install --cask mixxx

# Enable macOS virtual MIDI:
# Audio MIDI Setup → Window → Show MIDI Studio → IAC Driver → "Device is online" → Apply

# Copy the Mixxx mapping into Mixxx's controllers folder
DEST="$HOME/Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx/controllers"
cp deckpilot/adapters/mappings/mixxx.midi.xml "$DEST/DeckPilot.midi.xml"
cp deckpilot/adapters/mappings/mixxx.midi.js  "$DEST/DeckPilot.midi.js"

# Launch Mixxx: Preferences → Controllers → IAC Driver Bus 1
# → load "DeckPilot" → check "Enabled" → Apply
# Load two tracks onto deck 1 and deck 2.
```

**Run the React + FastAPI dashboard** (the polished version):

```bash
uvicorn backend.main:app --port 8000 --reload          # in one terminal
cd frontend && npm install && npm run dev              # in another
# Open http://localhost:5173
```

The LLM parser shells out to the `claude -p` CLI (uses your existing Claude Pro subscription, zero metered cost — [D-007](docs/DECISIONS.md)). Install Claude Code from <https://claude.com/claude-code> if you don't have it.

> **Setup pitfalls** (only one Python process can hold the IAC port at a time, IAC must be online before launch, etc.) — see [`docs/GOTCHAS.md`](docs/GOTCHAS.md).

---

## Supported actions

Thirteen typed actions in the vocabulary. Multi-step transitions are *composed* by the LLM, not hardcoded:

| Action          | Example phrase                                                |
|-----------------|---------------------------------------------------------------|
| `play_deck`     | *"play deck 1"*, *"drop deck 2"*                              |
| `pause_deck`    | *"pause deck 2"*                                              |
| `set_crossfader`| *"crossfader to the middle"*                                  |
| `fade_to_deck`  | *"fade to deck 2 over 8 seconds"*                             |
| `loop_deck`     | *"loop deck 1 for 4 beats"*, *"loop 32 beats"*                |
| `nudge_deck`    | *"nudge deck 2 forward"*                                      |
| `set_eq`        | *"kill the bass on deck 1"*                                   |
| `set_volume`    | *"deck 2 volume to 80%"*                                      |
| `set_filter`    | *"low pass deck 1"*, *"filter off"*                           |
| `set_fx`        | *"fx 1 to 50% on deck 1"*                                     |
| `set_pitch`     | *"pitch deck 1 up 4%"*                                        |
| `hot_cue`       | *"jump to cue 3 on deck 1"*                                   |
| `sync`          | *"sync deck 2"*                                               |
| `load_track`    | *"queue a daft punk track"* — library-aware                   |

**Agent schedule triggers** (D-021 + D-023):

| Trigger          | Example phrase                                                      |
|------------------|---------------------------------------------------------------------|
| `Immediate`      | *"... then ..."* — fires at schedule start                          |
| `DeckPosition`   | *"... when deck 1 is near end ..."* — fires at playhead fraction    |
| `AfterBeats`     | *"... in 16 beats ..."* — fires after N beats counted on a deck     |

---

## Status

**v0.3.** React + FastAPI frontend, agent layer with beat-aware triggers, 13 typed actions, 100 parametrized tests passing, 45-case eval at 100% with documented limitations. macOS-only.

---

## Why this exists

I built DeckPilot to prove I can ship an end-to-end AI product, not just talk about one. Most AI PM portfolios are RAG chatbots; I wanted something real-time, creative, with hard constraints (audio latency, hardware integration, musical correctness) — the kind of product where prompt design and scoping discipline visibly matter. The intersection of LLMs and a real-time creative tool felt underexplored. So I prompted Claude to build it, made every decision along the way, and documented the loop.

If you're hiring for AI product roles and this kind of work is what your team does day-to-day, I'd love to talk.

— [Mikka Arumugam](https://github.com/mikkaarumugam)
