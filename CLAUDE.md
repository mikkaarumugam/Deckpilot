# CLAUDE.md — DeckPilot

This file is loaded automatically by Claude Code at the start of every
session in this repo. Read it before doing anything else.

> ## ⚠️ Active migration in progress (2026-05-23 →)
>
> A React + FastAPI rewrite is underway on branch `feature/react-frontend`.
> The full plan, checklist, and resume guide live in
> [docs/MIGRATION.md](docs/MIGRATION.md). The decision rationale (which
> supersedes D-014's earlier deferral) is in
> [docs/DECISIONS.md](docs/DECISIONS.md) § **D-018**.
>
> **If you're a fresh session picking this up:**
> 1. Read `docs/MIGRATION.md` first — it has the six-phase checklist with
>    `[x]` / `[ ]` markers showing exactly which phase to resume from.
> 2. The Python brain (`deckpilot/`) is intentionally untouched. The new
>    code lives in `frontend/` (Vite + React + TS) and `backend/` (FastAPI
>    wrapping `deckpilot/` via HTTP).
> 3. Streamlit at `app/dashboard.py` is the working fallback and stays in
>    place. **Only one Python process can hold the IAC MIDI port at a
>    time** — quit Streamlit before running FastAPI.
> 4. Visual reference for the new UI is in `design/` (3 .jsx files).

## What is DeckPilot

A natural-language control layer for DJ software. You type or speak a
high-level DJ command — "play deck 1", "kill the bass on deck 1",
"bass swap into deck 2 over 4 seconds" — and DeckPilot parses it into
a structured **ActionPlan**, then executes it through a software adapter.
Today the adapter targets **Mixxx** via the macOS **IAC Driver** (virtual
MIDI).

Portfolio context: this is the user's AI-PM application portfolio piece.
The deliverables that matter are (a) a demo video, (b) `docs/EVAL.md`
showing accuracy + latency + failure-mode taxonomy, (c) a polished
README. **The eval doc is the most important artifact** — it's what
signals "this person thinks like an AI PM."

## Architecture in 10 seconds

```
text  ──▶  parser ──▶ ActionPlan ──▶  executor ──▶  MidiAdapter ──▶ IAC ──▶ Mixxx
        (regex|LLM)                 (timeline)    (note/CC table)
```

Two parsers: **regex** for the canonical phrasings (microseconds, free),
**LLM** (Claude Haiku via `claude -p` CLI subprocess) for paraphrases
and multi-step plans. Plan-level abstraction lets the LLM emit
coordinated multi-step transitions (bass swap, fade-then-loop).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full version.

## Where things live

```
deckpilot/
├── core/
│   ├── actions.py          ← DJAction dataclasses + ActionPlan + TimedAction
│   ├── executor.py         ← runs ActionPlans, expanding FadeToDeck into a stream
│   ├── undo.py             ← inverse_action / inverse_plan / reset_plan
│   └── parser/
│       ├── __init__.py     ← facade: regex first, fall back to LLM
│       ├── regex.py        ← rule list, ~12 patterns currently
│       ├── llm.py          ← claude -p subprocess + JSON validation
│       └── errors.py       ← shared ParseError
├── adapters/
│   ├── base.py             ← Adapter interface
│   ├── midi.py             ← MidiAdapter (python-rtmidi → IAC Driver)
│   ├── midi_feedback.py    ← MixxxFeedback (Mixxx → Python state read-back)
│   └── mappings/
│       ├── mixxx.midi.xml  ← Mixxx-side bindings + outputs (note/CC ↔ control)
│       └── mixxx.midi.js   ← JS handlers: play/pause + scripted BPM output
├── library/
│   ├── __init__.py         ← exports LibraryReader, Track
│   └── reader.py           ← read-only Mixxx SQLite library access
├── __main__.py             ← CLI entry. Subcommands OR NL string.

app/dashboard.py            ← Streamlit frontend
scripts/send_test_note.py   ← Sanity test: Python → IAC → Mixxx
tests/test_parser.py        ← 47 parametrized tests for regex
tests/eval.py               ← the eval harness backing docs/EVAL.md
docs/                       ← ARCHITECTURE, DECISIONS, ROADMAP, GOTCHAS, EVAL, …
```

## How to run things

```bash
# Activate venv (always — Python project)
source .venv/bin/activate

# Tests
pytest tests/test_parser.py -q

# CLI (explicit subcommand)
python -m deckpilot play --deck 1

# CLI (natural language; needs Mixxx running + DeckPilot mapping loaded)
python -m deckpilot "bass swap into deck 2 over 4 seconds"

# Streamlit dashboard
streamlit run app/dashboard.py
```

Before any of those work end-to-end, Mixxx must be open with the
**DeckPilot** mapping loaded on **IAC Driver Bus 1**, and the macOS
IAC Driver must be enabled. See `docs/GOTCHAS.md` for the setup pitfalls
already encountered.

## Conventions / patterns to keep

- **Adapter pattern is sacred.** The `MidiAdapter` only knows how to
  send one MIDI message per call. FadeToDeck is composite — expanded by
  the executor, not the adapter. Don't push composition into the adapter.
- **Parser always returns ActionPlan**, never a bare DJAction. Single
  commands wrap in `ActionPlan.single(...)`. The CLI and dashboard both
  use `executor.run_plan()`.
- **Note/CC numbers in `midi.py` MUST match `mixxx.midi.xml`.** They're
  paired; if you change one, change the other. Both files have header
  comments warning about this.
- **Prompt design is product design.** Many "bugs" are actually prompt
  issues. See the May 20 commit `b84ec8c` for an example of fixing
  declines by editing the system prompt instead of writing Python.

## Conventions to avoid

- **Don't add per-action confirmation dialogs.** The product is real-time
  creative — we picked plan-visible-before-audio + one-click undo over
  blocking confirmations. See `docs/DECISIONS.md` § "No confirmation".
- **Don't switch to the Anthropic SDK without explicit user request.**
  We deliberately route through `claude -p` to use the user's Claude
  subscription instead of a metered API key. SDK swap is documented
  as a future option but isn't on by default.
- **Don't expand the LLM action vocabulary without updating both the
  system prompt AND the JSON validator in `llm.py:_payload_to_action`.**
  Out of sync = silent failures.
- **Don't blindly add more LLM features.** Each addition cuts the
  hit-rate of the regex fast path. Prefer adding regex rules for
  predictable phrasings; reserve LLM for genuine paraphrase + composition.

## Pitfalls already learned (full list in docs/GOTCHAS.md)

- VirtualDJ Home throttles MIDI controllers to 10 minutes/launch. **Use
  Mixxx**, not VDJ.
- MIDI `note_on velocity 0` is spec-equivalent to `note_off` and gets
  dropped by Mixxx's `<normal/>` bindings. Play/pause uses JS script
  bindings to work around this.
- Streamlit hot-reloads function-body changes but NOT new imports.
  Adding a new exported symbol from another module requires a full
  Streamlit restart, not just a browser refresh.
- Mixxx audio output sometimes defaults to a disconnected device. If
  decks visibly play but no sound: Preferences → Sound Hardware →
  set Master to MacBook Air Speakers.

## Working style (read before responding)

These are the user's preferences, learned over the build. Honor them
unless explicitly told otherwise.

- **The user is still learning Python.** Comments in new code should
  lean educational where the *why* isn't obvious from the *what*. Not
  per-line; just when a non-obvious decision warrants it (one short
  line is plenty).
- **Be terse in responses.** Skip the recap of what you just did — the
  diff says it. End-of-turn summary is one or two sentences. When
  explaining concepts (architecture, decisions, debugging), be more
  generous — that's where the user is leveling up.
- **Build incrementally and commit at each milestone.** This project
  has 13+ commits, each with a meaningful scope. Match that cadence.
  Commit message format: `type(scope): short summary` (e.g. `feat(ui):
  ...`, `fix(llm): ...`, `docs: ...`).
- **Ask before destructive actions.** `rm`, `git push --force`, `git
  reset --hard`, dependency changes outside the agreed list. The
  user's permission config in `.claude/settings.local.json` codifies
  this — respect it.
- **Default to "execute, then show" not "show, then ask".** The
  user values flow. When suggesting changes, propose them concisely
  and just do them; don't lay out 5 options and stop.
- **Make trade-offs explicit, not invisible.** If you cut something or
  pick one approach over another, say WHY in one line. This is how
  the user is learning to think like a PM.
- **For UI / portfolio decisions, lean opinionated.** The user is
  building this for a job application; recommend the path that
  maximizes signal to AI PM hiring managers and call it out as such.
- **Don't propose voice input integrations.** The user has WhisperType
  installed locally; it dictates into any focused input. Voice is a
  solved problem from the system's perspective.
- **Track agent / UI / eval threads in todos, not as tangents.** The
  user wants the parked threads to stay visible. Use TodoWrite when
  introducing or resuming them.

## Where to pick up next

1. **Thread 4: the agent question** — beat-aware scheduling, state
   read-back from Mixxx, autonomous transitions. This is the biggest
   remaining work item. See `docs/ROADMAP.md`.
2. **UI redesign** — current Streamlit dashboard has grown busy. Worth
   sketching 2-3 alternative layouts.
3. **EVAL.md** — the AI PM artifact. ~30 prompts, accuracy + latency +
   failure-mode taxonomy.
4. **Demo video + README polish + GitHub push.**

Check `docs/ROADMAP.md` for the up-to-date status before suggesting
anything new.
