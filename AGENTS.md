# AGENTS.md

Cross-tool entry point for any AI coding assistant working on this repo
(Claude Code, Cursor, Aider, GitHub Copilot, Codex, GPT/Gemini sessions,
etc.). Tools that don't auto-load assistant context files should be
pointed here manually.

## Start here, in this order

1. **`CLAUDE.md`** at the repo root — project summary, architecture in
   10 seconds, file map, conventions to keep, conventions to avoid,
   pitfalls already learned. Claude Code auto-loads this; other tools
   should read it as the primary onboarding doc. ~100 lines.
2. **`docs/ROADMAP.md`** — what's shipped, what's next, what's
   deferred. Read this BEFORE proposing new work so you don't suggest
   something already done or already rejected.
3. **`docs/DECISIONS.md`** — ADR log explaining the *why* behind every
   major architectural choice. Skim before disagreeing with anything
   you see in the code; the trade-off is likely already documented.
4. **`docs/GOTCHAS.md`** — every debugging trap we've already paid for.
   Read this before debugging anything weird; the answer may already
   be there.
5. **`docs/ARCHITECTURE.md`** — full system explainer with pipeline
   diagram, action vocabulary, executor design, frontend layers.
6. **`docs/AGENT_DESIGN.md`** — design notes for the *agent layer*
   (Thread 4), the biggest pending feature. Read if proposing
   autonomous/scheduling/state-aware work.
7. **`docs/INTERVIEW_NARRATIVE.md`** — the portfolio storytelling
   document. If you're helping the user prep for an interview or
   write up the project, this is the canonical framing.

## House rules for AI assistants

These are also in `CLAUDE.md` under "Conventions" — repeated here for
tools that don't auto-load `CLAUDE.md`.

- **Adapter pattern is sacred.** `MidiAdapter` only sends one MIDI
  message per call. Composition lives in the executor.
- **Parser always returns `ActionPlan`**, never a bare `DJAction`.
- **Note/CC numbers in `midi.py` must match `mixxx.midi.xml`.** Both
  files document this requirement.
- **Don't switch to the Anthropic SDK without explicit user request.**
  We deliberately route through `claude -p` to use the user's
  subscription.
- **Don't add per-action confirmation dialogs.** Plan-visible-before-
  audible + one-click undo is the chosen UX.

## Project at a glance

DeckPilot is a natural-language control layer for DJ software (Mixxx
today). User types or speaks; the system parses to a structured
`ActionPlan` (one or more timed atomic DJ actions); an executor walks
the plan and dispatches each action through a `MidiAdapter` to Mixxx
via the macOS IAC Driver.

It's the user's AI Product Manager portfolio piece. The artifacts that
matter for that audience are: a demo video, `docs/EVAL.md` (currently
a placeholder — top priority pending work), and a polished README.

Single-user, local-only by design. No deployment, no cloud, no auth.

## When in doubt

Ask before making structural changes. Many decisions look arbitrary
but have a real `docs/DECISIONS.md` entry behind them.
