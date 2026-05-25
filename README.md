# DeckPilot

> **I'm looking for AI product roles.** I don't write code. I prompt, scope, evaluate, and direct. DeckPilot is the artifact of that loop applied to a real-time AI product, built in one weekend.

**Talk to your decks.** Type a DJ command — *"echo deck 1 out into deck 2"*, *"in 16 beats filter sweep back to deck 1"* — and an AI parses it, plans a multi-step musical move, and executes it inside [Mixxx](https://mixxx.org) via virtual MIDI. The agent layer counts beats and fires transitions autonomously.

https://github.com/user-attachments/assets/4dcd1f69-4b4d-43d0-94e9-b86f40e5d8dc

*Two Daft Punk tracks. Five commands. One AI doing the mixing.* ([fallback download](docs/demo.mp4))

---

## What's kind of crazy about this

Most "AI PM portfolio" projects are RAG chatbots that show three working examples. This one ships with:

- **A [45-case eval suite](docs/EVAL.md)** with methodology, latency p50/p95, source-split (regex vs LLM), and a failure-mode taxonomy. Most AI demos never measure whether the AI gets it right.
- **[23 architecture decision records](docs/DECISIONS.md)** documenting every product call — context, alternatives considered, trade-offs, what I'd change in production.
- **An autonomous agent layer** that counts musical beats in real time and fires transitions on its own. Goal-style prompts in, multi-step musical plans out.
- **A real-time creative product, not a chatbot.** Hard constraints — audio latency, hardware integration, musical correctness — the kind that punish loose thinking.

Every line of Python and TypeScript was written by Claude. Every decision about what to build, why, and what to cut was mine. **That's the AI PM loop.** The product is the artifact; the skill being demonstrated is the loop.

---

## What this proves about me as an AI PM

**I can scope ruthlessly.** I cut stems isolation, multi-tenant deployment, voice integration, hardware controller support, and three other features that didn't survive the weekend budget. [`docs/ROADMAP.md`](docs/ROADMAP.md) lists what's in, what's deferred, and what I explicitly won't build.

**I think in failure modes, not happy paths.** The eval doc has a [failure-mode taxonomy](docs/EVAL.md). The undo system, the plan-visible-before-audible UX, and the "no confirmation" decision are all designed around bounded cost-of-error — not preventing errors that can't be prevented.

**I pivot fast when the architecture supports it.** First target was VirtualDJ. After ~30 min I discovered VDJ Home throttles unrecognized MIDI controllers to 10 minutes per launch — actions silently no-op past that. Pivoted to Mixxx in under an hour because the adapter pattern was already drawn ([D-002](docs/DECISIONS.md)). Same weekend: pivoted from Anthropic SDK to `claude -p` CLI to avoid metered API costs ([D-007](docs/DECISIONS.md)). Both swaps shipped because the boundaries were right.

**I treat the prompt as the product.** The AI picks *bass swap* vs *filter sweep* vs *echo out* vs *drop swap* based on the verb in your command. Not because of model capability — because I gave it four distinct few-shot examples keyed to four distinct verbs. One prompt edit unlocks four genuinely different musical behaviours from the same model. That's the production lever most AI demos never touch.

**I measure trust quantitatively.** The 45-case eval defines what "correct" means in writing, with falsifiable assertions and a methodology that handles the LLM's non-determinism. The accuracy number isn't the signal — **the methodology is**.

**I know when to *not* ask.** Real-time creative tools die under confirmation dialogs. I replaced "ask permission" with three things together: parsed plan renders *before* audio fires (eyes confirm before ears), one-click undo on everything reversible (bounded cost-of-error), and the eval suite (earned right to act). Full reasoning in [D-008](docs/DECISIONS.md).

---

## What I directed vs what Claude wrote

| I did | Claude did |
|---|---|
| Scoped the product to "natural language → MIDI → Mixxx" and cut everything else | Wrote ~3,000 lines of Python + TypeScript |
| Decided the structured action vocabulary (LLM emits typed actions, never raw MIDI) | Implemented the dataclasses, executor, adapter, parser |
| Chose Mixxx over VDJ after the 10-min throttle bug | Wrote the Mixxx MIDI mapping XML + JS scripts |
| Designed the four-tier capability stack (translate → compose → reason → autonomous) | Built each tier when I asked |
| Wrote every system prompt — the four transition styles, the deck-default rule, the JSON validator schema | Tested prompts, surfaced failures, suggested fixes |
| Authored the 45-case eval methodology and what counts as "correct" | Wrote the eval harness |
| Made every architecture-decision call documented in [`DECISIONS.md`](docs/DECISIONS.md) | Captured the *why-not-what* in writing |
| Picked Haiku over Sonnet/Opus and articulated when to upgrade | Wired the model selector |
| Designed the demo above (track pairing, transition arc, voiceover beats) | None — the demo is mine |

**The product is what I shipped. The skill being demonstrated is the loop.**

---

## How the demo works, walked through

1. `play deck 1` — *Around The World* drops. Regex fast-path, sub-millisecond parse.
2. `loop deck 1 over 8 beats` — loop holds the chorus, builds tension.
3. `exit loop` — release.
4. `echo deck 1 out into deck 2 over 8 seconds` — *Around The World* trails into FX wet as *One More Time* fades in. The AI picks an FX-led transition because of the verb "echo," not a generic crossfade.
5. `in 16 beats filter sweep back to deck 1` — agent schedule. DeckPilot counts beats off *One More Time* and autonomously sweeps the filter back on beat 16. I do nothing for ~7 seconds; it runs the mix.

The single architectural call worth flagging: **the AI never emits raw MIDI.** It emits one of 13 typed actions; a deterministic Python layer translates each into MIDI. That gives testability, safety, and portability — the VirtualDJ → Mixxx pivot took an hour because of this. Full explainer: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## The docs are the product

These are the artifacts a hiring manager should actually open:

| File | What it shows |
|---|---|
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | **23 architecture decision records.** Every major call (action vocabulary, prompt design, no-confirmation UX, model selection, agent triggers) with context, alternatives considered, and trade-offs. Newest first. The PM thinking artifact. |
| [`docs/EVAL.md`](docs/EVAL.md) | **45-case parser eval** with methodology, failure-mode taxonomy, latency p50/p95, source split, and "what I'd change in production." Trust via measurement. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Shipped milestones, next priorities, explicitly-out-of-scope. Scoping discipline made visible. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline explainer, action vocabulary, executor design. |
| [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md) | Why musical-time triggers exist, the state-in-runtime vs state-in-trigger debate, what's parked for v0.4. |
| [`docs/GOTCHAS.md`](docs/GOTCHAS.md) | Every debugging trap I paid for. The honest version of what shipping involved. |
| [`docs/INTERVIEW_NARRATIVE.md`](docs/INTERVIEW_NARRATIVE.md) | How I tell this story in interviews — 60-second pitch, Q&A, the senior-PM lines worth memorizing. |
| [`CLAUDE.md`](CLAUDE.md) | What I tell Claude at the start of every session in this repo. The "system prompt" for my engineering loop. |

---

## Try it yourself

macOS only. Requires Mixxx (free) + Claude Code CLI (uses your Claude subscription, no API costs).

```bash
git clone https://github.com/mikkaarumugam/Deckpilot.git && cd Deckpilot
python -m venv .venv && source .venv/bin/activate
python -m pip install -e .
brew install --cask mixxx

# Enable macOS virtual MIDI:
# Audio MIDI Setup → Window → Show MIDI Studio → IAC Driver → "Device is online" → Apply

# Install the Mixxx mapping:
DEST="$HOME/Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx/controllers"
cp deckpilot/adapters/mappings/mixxx.midi.xml "$DEST/DeckPilot.midi.xml"
cp deckpilot/adapters/mappings/mixxx.midi.js  "$DEST/DeckPilot.midi.js"

# Launch Mixxx → Preferences → Controllers → IAC Driver Bus 1
# → load "DeckPilot" → check Enabled → Apply. Load tracks onto decks 1 and 2.

# Run the dashboard:
uvicorn backend.main:app --port 8000 --reload          # in one terminal
cd frontend && npm install && npm run dev              # in another
# Open http://localhost:5173
```

Full setup pitfalls in [`docs/GOTCHAS.md`](docs/GOTCHAS.md).

---

## Status

**v0.3.** React + FastAPI frontend, agent layer with beat-aware triggers, 13 typed actions, 100 parametrized tests passing, 45-case eval at 100% with documented limitations. macOS-only.

---

## Why this project exists

To prove I can ship an end-to-end AI product, not just talk about one. Most AI PM portfolios are RAG chatbots; I wanted something real-time, creative, with hard constraints (audio latency, hardware integration, musical correctness) — the kind of product where prompt design and scoping discipline visibly matter. The intersection of LLMs and a real-time creative tool felt underexplored.

So I prompted Claude to build it, made every decision along the way, and documented the loop.

**If you're hiring for AI product roles and this is what your team does day-to-day, I'd love to talk.**

— [Mikka Arumugam](https://github.com/mikkaarumugam)
