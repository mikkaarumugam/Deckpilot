# DECISIONS

Architectural decision log. Each entry is short on purpose: the *why*
matters more than the *what* (the code is the what). Newest first.

---

## D-013 · Default deck = 1 when LLM gets ambiguous input
**Date:** 2026-05-20 · **Commit:** `b84ec8c`

**Context.** Real testing surfaced LLM refusals on commands without
explicit deck ("turn bass on", "stop loop") — it returned `"unknown":
"deck not specified"`. Bad UX.

**Decision.** Edit the system prompt to (a) explicitly default to deck 1
when not specified, (b) provide a vocabulary mapping table (kill / cut /
drop → 0.0; bring back / restore → 1.0), (c) tighten the refusal
definition to "only for things genuinely outside the action vocabulary."

**Trade-off.** "Deck 1 default" is wrong if the user's working on deck 2.
Mitigated by showing the parsed plan in the dashboard so the deck is
visible before audio fires; user re-issues with explicit deck if wrong.

**Status.** Active. Will revisit once we have state read-back from Mixxx
(track "last-touched deck").

---

## D-012 · Plan-visible-before-audio instead of explicit confirmation
**Date:** 2026-05-20 · **Commit:** `658b757`

**Context.** When AI products misinterpret intent and just *act*, users
lose trust. The naive fix is to add a "are you sure?" confirmation per
action. For real-time creative tools (DJ, music production, drawing),
that destroys flow.

**Decision.** Replace explicit confirmation with three combined
mechanisms: (a) render the parsed plan table BEFORE audio fires
(implicit visual confirmation, no click required), (b) one-click ↶ undo
on every history entry (recovery is bounded by undo time, not action
permanence), (c) measure accuracy via the eval doc to defend the
no-confirmation choice with numbers.

**Trade-off.** Some actions are not cleanly invertible (Sync, HotCue,
NudgeDeck). Undo gracefully refuses on those. Crossfader undo snaps to
0.5 rather than restoring the precise prior value because we don't
snapshot state.

**Status.** Active. Documented as the answer to "why no confirmation?"
in any future review.

---

## D-011 · Multi-action ActionPlan, executor walks a flat timeline
**Date:** 2026-05-20 · **Commit:** `c86fbec`

**Context.** Single-action parsing means "bass swap" can't work
end-to-end — it's inherently a sequence. Three options: (a) hardcode a
"bass swap" action; (b) threading; (c) flatten plans into a single
timeline of atomic events.

**Decision.** Option (c). The parser returns `ActionPlan(steps=
tuple[TimedAction])`. The executor expands any composite step
(FadeToDeck) into atomic SetCrossfader events with their own
`at_seconds`, sorts the whole timeline, and walks it with `time.sleep`.

**Trade-off.** A FadeToDeck's individual SetCrossfader events get
duplicated when expanded; doesn't matter for our scale. We don't use
threading so a 4-second fade blocks the executor for 4 seconds — fine
for single-user CLI, would need rethinking for concurrent users.

**Status.** Active. This is also the substrate for the future agent
layer (Thread 4): an agent emits an ActionPlan; same executor runs it.

---

## D-010 · Bass swap via EQ trickery, not Mixxx stems
**Date:** 2026-05-20 · **Commit:** `c86fbec`

**Context.** Mixxx stems were introduced in 2.6 beta (May 2025). The
user has Mixxx 2.5.6 stable. Options: (a) upgrade to 2.7-alpha for real
stems, (b) implement bass swap via EQ low-cut trickery on 2.5 stable.

**Decision.** Option (b). EQ-based bass swap is the canonical
30-year-old DJ technique used by real club DJs because most tracks
aren't stem-separated. We pre-cut deck 2's bass with SetEQ, fade the
crossfader, kill deck 1's bass at the fade midpoint, restore deck 2's
bass at fade end. Same musical result without the alpha install risk.

**Trade-off.** Sounds slightly less clean than per-stem mute, but
"taught the system real DJ technique" is a stronger portfolio story
than "I clicked the stems checkbox."

**Status.** Active. When Mixxx 2.6 stable lands, adding stems is a new
action type (SetStem) + 8 mapping bindings — architecturally drop-in.

---

## D-009 · Streamlit dashboard, not FastAPI + custom frontend
**Date:** 2026-05-20 · **Commit:** `446d164`

**Context.** We needed a frontend for the demo video. Options:
Streamlit (Python, fast, ugly defaults), Gradio (similar), FastAPI +
HTML/JS (more polish ceiling, more work).

**Decision.** Streamlit. 45 minutes to a working dashboard with text
input, presets, plan visualization, history. Standard for AI portfolio
demos so recruiters recognize the pattern.

**Trade-off.** Streamlit's design ceiling is real; custom CSS is painful;
reruns on every interaction limit certain UX patterns (live progress
during long operations is awkward). If we want polished animations and
custom widgets later, the migration to FastAPI+JS is a separate session.

**Status.** Active. Marked for redesign sketch (see ROADMAP) — the
current dashboard works but has accumulated features.

---

## D-008 · Haiku, not Sonnet or Opus, for the LLM parser
**Date:** 2026-05-20 · **Commit:** `777abae`

**Context.** Parsing is a classification task with constrained JSON
output. Default behavior was to use whatever Claude Code's default
model is (Sonnet or Opus).

**Decision.** Pin `--model haiku` on the `claude -p` invocation.
Haiku is ~2-3x faster on inference for negligible quality hit on
pattern-matching tasks where the system prompt does the heavy lifting.

**Trade-off.** Haiku is slightly less robust on unusual paraphrases.
The fix when accuracy drops is to route specific failure modes to
Sonnet, not to upgrade the default — tiered model use, not monolithic.

**Status.** Active. Should be measured in EVAL.md.

---

## D-007 · `claude -p` CLI subprocess, not the Anthropic SDK
**Date:** 2026-05-19 · **Commit:** `900346d`

**Context.** Need to call an LLM for paraphrase parsing. SDK requires
an API key + metered billing; user already has Claude Pro/Max
subscription which the Claude Code CLI uses.

**Decision.** Use `subprocess.run(["claude", "-p", prompt])` — routes
through the existing subscription, no metered cost, one fewer
dependency.

**Trade-off.** ~400-500ms subprocess spawn overhead per call (vs
~50ms for SDK's warm HTTP client). No prompt caching (only in the SDK
path). For single-user portfolio scope, the win on cost/auth outweighs
the latency loss.

**Status.** Active. Swap to SDK is documented as a ~30-line change in
`llm.py` and is the path forward if/when we want concurrent calls or
prompt caching.

---

## D-006 · Two-tier parser: regex first, LLM fallback
**Date:** 2026-05-19 · **Commit:** `900346d`

**Context.** Pure regex can't handle paraphrases; pure LLM is slow and
non-deterministic even for boilerplate commands like "play deck 1".

**Decision.** Facade pattern: try regex first (instant, free,
deterministic), fall through to LLM only when regex returns None.

**Trade-off.** Two systems to maintain. Regex coverage has to be kept
in sync conceptually with LLM behavior. Mitigated by limiting regex to
clearly canonical phrasings and letting LLM own everything else.

**Status.** Active. This is the architectural backbone. Every latency
optimization is "add more regex rules" (D-005 expanded this in
practice).

---

## D-005 · Add ~6 regex rules for common atomic phrasings
**Date:** 2026-05-20 · **Commit:** `b39d6d6`

**Context.** Latency profiling showed every command — even "play deck 1"
— was taking ~1s via the LLM path. The regex fast-path was only
catching a tight set of canonical phrasings.

**Decision.** Expand regex to cover bare "play"/"pause", EQ kill/cut/
drop/mute + restore/turn-on, sync, loop-off. Six new rules, ~20 new test
cases. Multi-step plans still go through LLM.

**Trade-off.** Regex rules can drift from the LLM's understanding —
e.g., the regex normalizes "lows" to "low" via a helper; the LLM might
normalize differently. So far no observed divergence.

**Status.** Active. Anytime a single-action phrasing shows up
repeatedly in real use, the right move is to add a regex rule, not to
re-prompt the LLM.

---

## D-004 · JS script bindings for Mixxx play/pause
**Date:** 2026-05-20 · **Commit:** `efb1bd1`

**Context.** Mixxx's `<normal/>` MIDI binding can't distinguish a
"play" message from a "pause" message on one note because MIDI's
"note_on velocity 0" is spec-equivalent to note_off, and Mixxx drops
note_off events before they reach the binding.

**Decision.** Use TWO different notes (60 = play deck 1, 61 = pause
deck 1, etc.) routed through `<script-binding/>` to JS handlers in
`mixxx.midi.js` that explicitly call `engine.setValue("[Channel1]",
"play", 1 or 0)`. This is the canonical Mixxx pattern.

**Trade-off.** Extra file to maintain (the JS), more bindings in XML.
Discoverable: real hardware mappings (Pioneer, NI) ship with hundreds
of similar JS handlers.

**Status.** Active.

---

## D-003 · Pivoted target from VirtualDJ to Mixxx
**Date:** 2026-05-19 · **Commit:** `c61cd09`

**Context.** Initial M1 testing in VirtualDJ kept failing: MIDI was
received but actions never fired. After ~30 minutes of debug, found
the cause: **VirtualDJ Home throttles unrecognized MIDI controllers
to the first 10 minutes after launch.** Past that, MIDI shows in the
UI but actions silently no-op.

**Decision.** Pivot to Mixxx (free, open-source, no licensing wall).
The adapter pattern made this a config change rather than a refactor —
new mapping XML, no code changes.

**Trade-off.** Mixxx is less popular than VDJ for clubs but more
appropriate for a reproducible portfolio piece — anyone watching the
demo can replicate it without buying anything.

**Status.** Active and load-bearing in the portfolio narrative —
*"my first pivot under fire"* is a real story.

---

## D-002 · Adapter pattern + action schema as the architectural backbone
**Date:** 2026-05-19 · **Commit:** `de0f9e2`

**Context.** Many "AI controls X" projects hardcode against one target
(one DJ app, one game, etc.). Hard to swap, hard to test.

**Decision.** Force every action through a structured `DJAction`
dataclass. The LLM emits one of N pre-defined shapes; the adapter
translates a shape into MIDI. Swapping the target DJ software is
writing a new adapter, nothing else changes.

**Status.** Validated by D-003 (the VDJ → Mixxx pivot landed in an
hour) and D-007 (the claude-p ↔ SDK swap is a self-contained ~30
lines).

---

## D-001 · Mixxx via virtual MIDI, not via Mixxx HTTP API
**Date:** 2026-05-19 · **Commit:** `de0f9e2`

**Context.** Mixxx exposes both MIDI-mappable controls and a (limited)
internal scripting API. Could control via either.

**Decision.** Virtual MIDI via macOS IAC Driver. MIDI is a 40-year-old
universal standard; the same code structure works against any
MIDI-capable DJ software (Mixxx, VirtualDJ, Serato, Traktor, hardware
controllers). The HTTP API is Mixxx-specific.

**Status.** Active and load-bearing in the portfolio architecture
story.
