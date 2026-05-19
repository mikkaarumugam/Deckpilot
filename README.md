# DeckPilot

**Talk to your decks.** A natural-language control layer for DJ software. You type a command — *"fade to deck 2 over 8 seconds"* — DeckPilot understands it, turns it into a structured action, and executes it inside VirtualDJ (or any DJ software with MIDI input) via a virtual MIDI cable.

This is a portfolio project demonstrating: LLM-driven structured output, adapter-pattern architecture, and AI evaluation methodology.

> 🚧 **Status:** weekend MVP in progress. See [`docs/ROADMAP`](#whats-next) at the bottom of this file.

---

## Demo

*(60-second demo video will go here once recorded.)*

---

## Architecture

```
   CLI text  ──▶  parser  ──▶  DJAction  ──▶  MidiAdapter  ──▶  IAC  ──▶  VirtualDJ
                 (LLM +                       (mapping.json)
                  regex)
```

The pipeline is deliberately small. The interesting design call is that **the LLM doesn't control VirtualDJ directly**. It produces a structured action (one of 6 well-defined types), and a separate non-AI layer executes it. That gives us:

- **Testability** — we can evaluate the LLM's parsing accuracy without VirtualDJ running.
- **Swappability** — replacing VirtualDJ with Mixxx or Serato is a new adapter, nothing else changes.
- **Safety** — the LLM can only emit actions from a fixed vocabulary. It can't ask for things the system doesn't support.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the long version.

---

## Quickstart

```bash
# 1. Clone and install
git clone <this-repo> && cd deckpilot
python -m pip install -e .

# 2. Enable macOS virtual MIDI
# Open Audio MIDI Setup → IAC Driver → check "Device is online"

# 3. Verify Python can see the MIDI port
python scripts/send_test_note.py

# 4. In VirtualDJ: MIDI Learn the test note to "play deck 1"

# 5. Run a command
python -m deckpilot "play deck 1"
python -m deckpilot "fade to deck 2 over 8 seconds"
```

Set your Anthropic API key for the LLM parser:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Supported actions (v0.1)

The 6 actions DeckPilot can execute:

| Action            | Example phrase                              |
|-------------------|---------------------------------------------|
| `play_deck`       | "play deck 1"                               |
| `pause_deck`      | "pause deck 2"                              |
| `set_crossfader`  | "crossfader to the middle"                  |
| `fade_to_deck`    | "fade to deck 2 over 8 seconds"             |
| `loop_deck`       | "loop deck 1 for 8 beats"                   |
| `nudge_deck`      | "nudge deck 2 forward"                      |

---

## Evaluation

See [`docs/EVAL.md`](docs/EVAL.md) — accuracy and latency of the LLM parser on 20 hand-written commands, with failure-mode categorization.

---

## What's next

Things explicitly **out of scope** for v0.1 that would be interesting next steps:

- **Voice input** (Whisper) so you can talk to DeckPilot mid-set.
- **MCP server** so Claude Desktop or an agent IDE can drive DeckPilot directly.
- **Mixxx and Serato adapters** — same action schema, different adapter.
- **VirtualDJ Pro HTTP** for richer state read-back (knowing beat position, current track, etc.).
- **Action plans** — "do a bass-swap transition" as a sequence of low-level actions, planned by the LLM.
- **Undo** — DJs don't trust magic; one-tap reversibility for the last action.

---

## Repo layout

```
deckpilot/                  importable package
  core/                     action schema, executor, parsers
    parser/
      llm.py                Anthropic SDK parser
      regex.py              regex fallback for common commands
  adapters/                 software-specific output adapters
    midi.py                 virtual MIDI via python-rtmidi
    mappings/virtualdj.json which MIDI notes/CCs map to which actions
scripts/send_test_note.py   verify IAC + python-rtmidi working
tests/test_parser.py        unit tests for the parser
tests/eval.py               run 20 prompts, dump accuracy/latency
docs/ARCHITECTURE.md
docs/EVAL.md
```
