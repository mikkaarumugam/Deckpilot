# DECISIONS

Architectural decision log. Each entry is short on purpose: the *why*
matters more than the *what* (the code is the what). Newest first.

---

## D-021 · Agent layer (Tier 2, demo-scoped) — goal-directed schedules
**Date:** 2026-05-23 · **Commit:** `a1a5327` · **Status: Shipped**

**Context.** Through D-020 the system was still a *smart MIDI controller*:
text in → ActionPlan → executor runs it → silence. Every action required
a user prompt. The "Thread 4 agent layer" was the parked direction —
specifically the **goal-directed planning** flavour: user gives a high-
level goal ("play X then auto-transition into Y when X is nearly done"),
system decomposes + executes autonomously, monitors playback, fires the
next step when its trigger condition hits.

Two factors made this newly cheap this session:
1. **Playhead position read-back** shipped earlier today (mirror of D-016/
   D-017's BPM pattern). Without position, "trigger when track is X% done"
   is impossible. With it, the trigger is one float comparison.
2. The substrate is otherwise complete — multi-step plans (D-011), auto-
   load (D-019), state read-back, library awareness, streaming (D-020).
   Nothing about the agent layer required rewriting prior work.

**Decision.** Add a new abstraction above ActionPlan:
- `Trigger` union: `Immediate` (fires on start) | `DeckPosition(deck, at)`
  (fires when deck N's playhead crosses fraction X).
- `ScheduledPlan = (Trigger, ActionPlan, label)` — a plan that waits for
  a trigger.
- `AgentSchedule = tuple[ScheduledPlan, ...]` — an ordered sequence.

Add a singleton `AgentRuntime` that holds at most one active
`AgentSchedule`, polls Mixxx state at 500ms, and fires each step's
ActionPlan via the existing Executor when its trigger condition hits.
Single `asyncio.Lock` serialises plan execution — manual `/execute`
requests can't race against scheduled firings.

Extend the LLM prompt with goal-decomposition guidance: when the user
describes a timed sequence ("then", "when X ends", "after"), Haiku emits
`{"schedule": [...]}` instead of `{"plan": [...]}`. Same JSON wire shape,
different top-level key — parser branches.

Three new routes (`POST /agent/start`, `POST /agent/cancel`,
`GET /agent/state`), one new React component (`AgentQueue`), one new
hook (`useAgentState`).

**Demo-scope limits** (deliberately punted to v0.4+):
- **Only two trigger types.** Beat-aware triggers (`AfterBeats(8)`,
  `OnDownbeat`) need beat-grid read-back — not shipped yet. The
  position-based trigger covers ~80% of useful agent behaviour without it.
- **No recovery / re-planning.** If the LLM emits a schedule with bad
  track assumptions (wrong duration, wrong BPM), the user cancels +
  re-prompts. A self-correcting scheduler is a much bigger build.
- **No multi-schedule queue.** Only one active schedule at a time.
- **No manual override mid-schedule.** Cancel is all-or-nothing.
- **No nested goals.** A ScheduledPlan's plan is a flat ActionPlan, not
  another schedule. Recursive schedules are unnecessary at this scope.

**Architectural framing.**
- `core/agent.py` lives next to `core/actions.py` + `core/executor.py` —
  it's a peer abstraction, not a layer above. The existing Executor still
  walks atomic timelines; AgentRuntime orchestrates *which* ActionPlans
  run *when*.
- The same `_payload_to_action` / `_payload_to_plan` helpers serialize
  schedules — no new action vocabulary, just a new envelope.
- Manual `/execute` still works unchanged. The agent layer is opt-in
  per-prompt based on what the LLM emits.

**Interview line.**
> *"DeckPilot now does goal-directed autonomous mixing. User describes a
> sequence; Haiku decomposes it into an AgentSchedule — a list of
> ActionPlans gated by trigger conditions (playhead position, immediate).
> A background scheduler polls Mixxx state at 500ms and fires each plan
> when its condition hits. Adding beat-aware triggers and re-planning
> would extend the same model; the architecture is right-sized for v0.4
> work."*

**Trade-offs accepted.**
- LLM reliability on schedule shape is the main failure mode. We mitigate
  with strict validation (`_payload_to_schedule` raises ParseError on any
  shape deviation) but Haiku may sometimes default to `{"plan": [...]}`
  even for goal-style prompts. Sonnet routing for this specific case is
  the documented escape hatch ([D-008](#d-008--haiku-not-sonnet-or-opus-for-the-llm-parser)).
- Position read-back has ~1/128 resolution. A `DeckPosition(at=0.92)`
  trigger may fire ~1-2 seconds early or late depending on where the CC
  step lands. Tolerable for the "transition near end" use case;
  surgical timing requires beat-grid awareness.
- Background polling runs at 500ms even when no schedule is active. The
  task idles cheaply but it's still a heartbeat. Could be event-driven
  later.

**Status.** Shipped 2026-05-23. The demo prompt of record:
> *"play berlioz la danse on deck 1, then when it's nearly done,
> auto-transition into highjack on deck 2 with a bass swap over 8 seconds"*

The Run button kicks off the schedule; AgentQueue shows the pending
"transition into highjack" step with a live countdown
("deck 1 → 23% to go"). When berlioz crosses 92%, the transition fires
autonomously. User does nothing for ~3 minutes.

That's the autonomous moment.

---

## D-020 · Stream LLM parses via Server-Sent Events, no API key swap
**Date:** 2026-05-23 · **Commit:** `fa1c2d6` · **Status: Shipped**

**Context.** Post-D-019, LLM parses still felt slow to use: ~2-7s of
static spinner between Enter and the plan appearing. Profiling on the
user's machine pinned the dominant cost to (a) Haiku's reasoning over
the ~1700-token static system prompt and (b) the `claude -p`
subprocess spawn (~500ms fixed). Library context was *not* the
bottleneck — only ~200 tokens for an 8-track library.

The obvious fix — switch to the Anthropic SDK with prompt caching —
violates [D-007](#d-007--claude-p-cli-subprocess-not-the-anthropic-sdk):
the project deliberately routes LLM calls through the user's existing
Claude Pro subscription to avoid metered API cost. The constraint stuck.

**Decision.** Stream the LLM response with **Server-Sent Events** over
HTTP. The frontend gets each plan step *as Haiku generates it* instead
of waiting for the full response. Wall-clock time is essentially
unchanged; **perceived** latency drops dramatically — first visible
motion in ~500ms instead of ~4s.

Pieces of the implementation:

1. `claude -p --output-format=stream-json --include-partial-messages
   --verbose` emits one JSON object per line as Haiku generates output.
2. New `deckpilot/core/parser/llm_stream.py` async-iterates the
   subprocess's stdout, filters to `content_block_delta` events of
   type `text_delta` (ignores `thinking_delta` — Haiku's chain-of-
   thought, not the structured output).
3. A **tolerant brace-counting parser** (`_StepExtractor`) feeds the
   text deltas and emits each completed plan-step JSON object as soon
   as its closing brace arrives. Not a full JSON parser — just enough
   to detect step boundaries inside the `"plan": [...]` array. Handles
   strings + escapes correctly.
4. New `POST /parse/stream` (FastAPI `StreamingResponse`) wraps each
   step + the final complete `ParseResponse` as SSE events: `started`,
   `step`, `complete`, `error`.
5. Frontend `api.parseStream(text)` is an async generator using
   `fetch` + `ReadableStream` (EventSource doesn't support POST). It
   yields typed `ParseStreamEvent`s the hook consumes via `for await`.
6. `usePilotFlow.runLlmParse` accumulates streamed steps into a
   growing `parseResult.plan`; `CommandCard` renders the plan area
   during the `parsing` phase with a "streaming next step…" indicator
   beneath the last row.

**Why SSE and not WebSocket.** SSE is one-way (server → client), which
is exactly what we need. It's plain HTTP, plays nicely with FastAPI's
existing CORS + lifespan setup, and degrades gracefully (browser auto-
reconnects on transient disconnects). WebSocket would have added
bidirectional plumbing for zero benefit.

**Trade-off accepted.** A tolerant brace-counter is fragile by design
— it makes assumptions about the LLM's output structure (objects
inside a `plan` array, no nested arrays of objects). The system prompt
already guarantees that shape; if it ever changes, the extractor
silently drops steps and the final `complete` event still delivers
the validated plan via the strict parser. So the worst case is "no
progressive reveal, only the final plan" — not a crash.

**Why this isn't violating D-007.** D-007 is about LLM *call*
mechanics — subscription vs metered API key. D-020 changes the
*streaming* of those calls. Independent concerns; no conflict. The
subprocess still runs `claude -p`; the user's Claude Pro subscription
still pays for inference.

**Free side-benefit observed.** Claude Code's CLI automatically
prompt-caches its own system context (~31k tokens, 5-minute TTL).
This means the second LLM call within 5 minutes runs noticeably faster
than the first — *without us doing anything special*. The streaming
UX makes this cache warmth visible: warm calls reveal the first step
in ~300ms, cold calls in ~1s.

**Status.** Shipped 2026-05-23 alongside D-019. See `llm_stream.py`,
`backend/routes/parse_stream.py`, `frontend/src/api/client.ts`
(`parseStream`), `usePilotFlow.ts` (`runLlmParse`), `CommandCard.tsx`
(`StreamingTail`).

---

## D-019 · GUI auto-load supersedes D-015's suggestion-only path
**Date:** 2026-05-23 · **Commit:** `fa1c2d6` · **Status: Shipped**

**Context.** D-015 (2026-05-22) concluded that Mixxx's controller-script
API exposes no path-based track load primitive across versions 2.5-2.7,
so `LoadTrack` actions were rendered as a **suggestion card** — the LLM
picks a track, the user manually drags it onto the deck. Honest UX,
matches the Cursor/Copilot "AI suggests, human accepts destructive
action" pattern.

The framing was right but the *manual drag* was hiding a stronger story:
DeckPilot is a **control panel that flies Mixxx**, not just a parser
that emits structured intent. With the user dragging tracks, the agent
loop has a hand-off where the human is the actuator. With auto-load,
the loop closes: text → plan → Mixxx acts.

**Decision.** Add a thin **GUI adapter** (`deckpilot/adapters/gui.py`)
that drives Mixxx via macOS `osascript`:

1. Copy `"{title} {artist}"` to the clipboard via `pbcopy`.
2. AppleScript: activate Mixxx, `Cmd+F` to focus library search, `Cmd+V`
   paste, `Return` to commit + move focus to the result list, `Down`
   to highlight row 1.
3. AppleScript: `Shift+Left` (deck 1) or `Shift+Right` (deck 2) — Mixxx's
   default "load selected to deck N" shortcut.
4. AppleScript: `Cmd+F`, `Cmd+A`, `Delete` to wipe the search and restore
   the full library view.

`MidiAdapter._dispatch_load_track` is now hybrid: if a `MixxxGuiAdapter`
is wired AND `LibraryReader.count_search_matches(query) == 1`, it
delegates to the GUI adapter. Otherwise it falls back to
`LoadTrackSuggestion` (the D-015 manual-drag card). The uniqueness check
is the safety net — without it, an ambiguous query could load the wrong
track silently.

**The architectural framing.** The adapter pattern stays clean. MIDI for
the canonical control surface (play, pause, EQ, crossfade, sync, hot
cues, loops); GUI for the one operation MIDI can't reach. Both adapters
expose narrow surfaces; routing happens in one place. A future Mixxx
release that adds a real load API would swap out *only* the GUI adapter.
Same shape would work for Traktor / Serato.

**The interview line.** *"Mixxx's controller API doesn't expose
path-based load — I verified across versions 2.5-2.7. So I split the
adapter: MIDI for everything the controller scripting covers, AppleScript
GUI automation for the one operation it can't. Bounded hybrid — GUI
automation lives in one function, called from one place, with an
explicit uniqueness guard and a graceful fallback to manual-drag when
the guard fails."*

**Preview + countdown UX preserves D-012's plan-visible-before-audio
principle.** When the backend marks the suggestion `auto_loadable:
true`, the frontend renders the card with a 1.5s countdown bar and a
**Cancel** button. The track + reasoning are visible before any audio
fires. If the user wants a different pick, they cancel and re-issue. If
they do nothing, /execute auto-fires and Mixxx loads the track.

**Trade-offs accepted:**
- **Focus-steal is visible.** Mixxx pops to front during the AppleScript
  flow. We framed this as a feature ("DeckPilot is flying Mixxx") rather
  than a bug. The interview narrative supports the framing.
- **macOS Accessibility permission required.** First run prompts the
  user; permanent after granting. Only blocks first-run flow.
- **Mixxx keyboard shortcuts assumed.** Defaults verified on the user's
  machine (`Shift+Left`/`Shift+Right` for load). A custom Mixxx keyboard
  map would break the load step — drop-in fix would be adding a
  `LoadSelectedTrack` MIDI binding to `mixxx.midi.xml` and dispatching
  via MIDI from the GUI adapter (no focus steal either, as a bonus).
- **Search-box uniqueness is approximate.** Our `count_search_matches`
  is conservative — checks tokens against title+artist only, while Mixxx
  also searches album/comment/genre. In practice, 1 here means 1 in
  Mixxx too for typical "Title Artist" queries; ambiguity falls back
  safely.

**Status.** Shipped 2026-05-23. D-015 stays in the log as the *prior
reasoning* — important because the journey (suggestion → auto-load) is
itself the AI PM story. D-015's suggestion-card render is still the
fallback path when the uniqueness check fails.

---

## D-018 · React + FastAPI rewrite (supersedes D-014's deferral)
**Date:** 2026-05-23 · **Branch:** `feature/react-frontend` · **Plan:** [docs/MIGRATION.md](MIGRATION.md) · **Status: Shipped**

**Context.** D-014 (2026-05-21) deferred the FastAPI + React rewrite as P2,
reasoning that EVAL.md and demo-video work were higher-leverage for AI PM
hiring than UI polish. Two days later, a Claude Design output produced a
genuinely-polished frontend reference (`design/pilot.jsx`, ~1275 lines) with
Geist + Instrument Serif typography, a coral-accent warm dark theme, animated
phase machine (typing → parsing → ready → running → done), and a streaming
plan reveal. The design quality flipped the original trade-off: visual upgrade
is now substantial enough to justify the ~10-12h cost.

**Decision.** Build the new frontend on `feature/react-frontend` over a
focused day. Reuse the existing `deckpilot/` Python package as the brain —
the new FastAPI backend is a thin HTTP wrapper around `parser`, `executor`,
`adapters/midi`, `adapters/midi_feedback`, and `library/reader`. No
rewriting of business logic; the brain is done. The Streamlit dashboard
(`app/dashboard.py`) stays in place during migration as a fallback and
remains the documented dev tool.

**Trade-off accepted.** Demo video + GitHub push + applications all delayed
by ~2-3 days. Real cost in a tough market. Justified IF the visual upgrade
genuinely lands better with hiring managers — testable empirically on the
demo video.

**What the migration explicitly keeps:**
- All AI PM signal artifacts: EVAL.md (29-case suite), DECISIONS log (this
  file), library awareness with LLM reasoning visible on suggestion cards.
- The `claude -p` subprocess for LLM calls (per D-007 — not switching to
  the Anthropic SDK).
- The adapter pattern with `python-rtmidi` → IAC Driver virtual MIDI.
- All 17 prior ADRs unchanged.

**What the migration deliberately defers** (documented as day-1 non-goals):
- WebSocket streaming of step.done events → replaced with 250ms HTTP polling
  for day 1. Real WS is a +2-3h follow-up.
- The design's "Tweaks" theme-swapper sidebar (`design/tweaks-panel.jsx`) —
  not user-facing.
- The auto-cycling demo loop in `usePilotFlow` — replaced with real
  user-driven state machine.
- Real backing of the queue UI — mocked as static for day 1.

**Why this isn't violating D-007 / D-008 (claude-p, Haiku model).** Those
ADRs are about LLM choice. This ADR is about UI choice. Independent
concerns; no conflict.

**Rollback path** (documented in MIGRATION.md):
```bash
git checkout main
git branch -D feature/react-frontend
rm -rf frontend backend     # if created
# Streamlit + everything else works as before
```

The branch is fully isolated until Phase 6 merges. Abandoning mid-way costs
only the hours already invested.

**Status.** **Shipped 2026-05-23** on branch `feature/react-frontend`
in six commits (`3cabfe5` → `088092d`). Total: ~6h, well under the
10-12h budget. Streamlit dashboard kept at `app/dashboard.py` as a
fallback; both apps coexist in the repo for the demo recording window.

**One mid-flight redesign worth noting** (D-018a). Phase 4 originally
shipped with **eager LLM parsing** — every keystroke debounce fired
`POST /parse` which called Haiku. The user noticed this was wasteful:
typing a paraphrase like "bass swap into deck 2 over 4 seconds" would
fire 2-3 partial LLM calls before completing. Mid-Phase-4 we pivoted
to **Pattern C**: regex parses eagerly (in-process, free, instant);
LLM only fires when the user presses Enter on a regex-no-match.
`POST /parse` gained a `mode: "auto" | "regex" | "llm"` field; mode=
"regex" returns `error: "no_regex_match"` as a sentinel so the UI can
show "(press ⏎ to ask Haiku)" hint without treating it as a real
error. Captures the best of both: canonical commands feel instant,
paraphrases are explicit, zero wasted LLM calls.

See [docs/MIGRATION.md](MIGRATION.md) for the per-phase checklist
(all checked) and the resume guide that's now of historical value.

---


---

## D-017 · BPM lookup via `file_bpm`, not `bpm`, for library matching
**Date:** 2026-05-22 · **Commit:** `e1c3b0e`

**Context.** The sidebar's live-state panel matches the BPM Mixxx
emits against the library DB to surface the loaded track's title.
First version subscribed to `[ChannelN].bpm` — the LIVE playback BPM.

**Problem found in testing.** Two issues with `bpm`: (a) it drifts as
the user pitch-nudges a deck, breaking the library match; (b) for
tracks Mixxx hasn't analyzed yet, `bpm` returns a non-zero ESTIMATE
which gives a confidently-wrong sidebar match.

**Decision.** Switch the JS `engine.makeConnection` subscription to
`file_bpm` — the canonical BPM stored in the track's metadata. It's
constant across the playback session, matches `library.bpm` directly,
and is `0.0` for un-analyzed tracks (which the sidebar then labels
honestly: "BPM not yet analysed").

**Trade-off.** We lose live-BPM tracking during pitch nudges. That's
fine — pitch nudges are a *transient* DJ technique; the library
identity of the loaded track doesn't change. State read-back is about
"which track is on which deck," not about pitch state.

**Status.** Active. See GOTCHAS for the related Mixxx-flushes-on-quit
behavior that complicates this even with `file_bpm`.

---

## D-016 · MIDI state read-back via `<output>` + JS scripted output
**Date:** 2026-05-22 · **Commit:** `e1c3b0e`

**Context.** Session 2 needed Python to *see* what Mixxx was doing
(play state, BPM) without polling or guessing. Mixxx exposes state via
several channels: standard `<output>` MIDI bindings (binary), scripted
JS output (continuous), HTTP API (2.6+ only — third-party in 2.5),
OSC (setup-heavy). All four are listed in `docs/AGENT_DESIGN.md`.

**Decision.** Hybrid MIDI: standard `<output>` for the binary case
(play state — fires when `[ChannelN].play` crosses 0.5), and scripted
JS output via `engine.makeConnection(group, "file_bpm", cb)` for the
continuous case (BPM, scaled 60–200 → 0–127 CC). Listen on the same
IAC bus we use for sending.

**Why this shape.**
- Zero new dependencies — we already had `python-rtmidi` for the send
  side; the input side is one extra port open.
- Symmetrical with the send-side architecture — Mixxx mapping XML is
  the single source of truth for the wire format in both directions.
- Bypasses the Mixxx 2.5 HTTP API limitation entirely; same code
  pattern would work for Mixxx 2.6+, Traktor, Serato, etc.

**Subtlety: the request-state handshake.** `makeConnection` fires
*once* on initial connect with the current value, but only when the
mapping is loaded (not when Python connects). So if Python opens the
input port *after* Mixxx's mapping already loaded, it sees no initial
BPM — only future changes. Fix: a `requestState` script-binding
(note 0x7F) that Python fires once on startup; JS re-broadcasts
current play state + BPM. Without this, the sidebar would render
"BPM: —" until the user did something in Mixxx.

**Status.** Active. Becomes the substrate for Thread 4 (agent layer)
since beat-aware scheduling needs current BPM + playhead position.

---

## D-015 · Library-aware LLM, but LoadTrack is a SUGGESTION, not auto-load
**Date:** 2026-05-22 · **Commit:** `9854fba` · **Status: Superseded by [D-019](#d-019--gui-auto-load-supersedes-d-015s-suggestion-only-path)**

> **Superseded 2026-05-23.** D-019 adds a GUI adapter (macOS `osascript`)
> that auto-loads when the title+artist uniquely identifies a library
> row. The manual-drag suggestion card from this ADR stays as the
> **fallback** path for ambiguous matches. The reasoning below is
> historical but still load-bearing for understanding why we didn't
> just hack around the API limitation immediately.

**Context.** Session 3's goal was library awareness: the LLM picks
tracks by artist/genre/BPM/vibe and loads them onto a deck. The first
spec said `MidiAdapter` would dispatch `LoadTrack` actions via "a
Mixxx MIDI binding for 'load selected track to deck N'." That binding
exists (`[ChannelN].LoadSelectedTrack`) but it loads whatever is
currently *highlighted* in Mixxx's library pane — there's no
path-based or library-ID-based load primitive in the controller-
script API in either Mixxx 2.5 *or* 2.6. The 2.6 changelog and
control-surface docs were verified — same set of load controls as
2.5; no new ones.

**Three load paths explored.**
1. **`open -a Mixxx <file>` (macOS).** Returns exit 0 silently;
   Mixxx accepts the open event but doesn't load the file. Verified
   via both `open` and `osascript ... open POSIX file`. Mixxx 2.5
   only honors openFiles at startup, not for already-running
   instances.
2. **Library-navigation hack (MoveTop + N×MoveDown + LoadSelected).**
   Doable but fragile — any user click in Mixxx's library pane
   (playlist, search, sort) invalidates the row count. Hard to demo
   reliably.
3. **Upgrade to Mixxx 2.6/2.7.** Verified against the 2.6 manual and
   GitHub changelog: no new load APIs. One-way DB migration risk for
   zero benefit.

**Decision.** Keep `LoadTrack` as a typed action emitted by the LLM,
but the executor's adapter raises `LoadTrackSuggestion` carrying the
resolved `Track`. The dashboard catches that and renders a styled
"AI suggests for deck N" card with title/artist/BPM/key/genre. The
rest of the plan does NOT execute (subsequent steps would target an
unloaded deck and silently misfire). The user loads manually if they
want to follow the suggestion.

**Trade-off.** Demo is no longer hands-off-Mixxx for library-load
commands — the user does one drag onto the target deck. For
bass-swap or EQ commands on already-loaded tracks, it stays fully
autonomous.

**Why this is the right portfolio answer.** "AI suggests, human
accepts" is the dominant agent pattern in shipped products (Cursor
Compose, ChatGPT plugins, Claude Computer Use). Loading a different
track is a *destructive* action (overwrites the deck's current
content) — confirmation is product-appropriate, not a regression.
The interview line: *"I scoped the auto-load when Mixxx's API made it
infeasible; cutting that and keeping a clean human-in-the-loop
confirmation is a more honest UX for AI products anyway."*

**Status.** Active. If a future Mixxx version exposes a path-based
load API, the only change is the `MidiAdapter._dispatch_load_track`
body — same `LoadTrack` action, same dashboard wiring still works.

---

## D-014 · Defer FastAPI + React migration (P2)
**Date:** 2026-05-21

**Context.** Streamlit's design ceiling is real — even with the Linear-
style theme + custom CSS, ~30% of visual polish is locked behind
Streamlit's chrome. A FastAPI + React/Tailwind rewrite would deliver
pixel-perfect UI with animations, hover states, real-feel interactions.

**Decision.** Defer. Focus on the AI PM portfolio essentials first:
EVAL.md, demo video, README polish, GitHub push. Revisit React
migration as a P2 task after the portfolio is shippable.

**Trade-off.** Streamlit ships with default chrome that's recognizable
as "AI demo." A React app would read as "polished product." For AI PM
hiring specifically, EVAL.md is more differentiating than visual
polish, so the time budget is better spent there. For consumer/design-
heavy PM roles, the calculus might flip.

**If we revisit:** the architecture is designed for this swap.
~4 hours total — FastAPI shim (~45 min) exposing the existing parser/
executor/adapter as HTTP endpoints, React app generated via claude.ai
Artifacts (~30 min iterating), wiring (~1-2h), optional deploy
(~30 min). The Python backend doesn't move.

**Status.** Deferred. Listed in ROADMAP.md "Deferred" section.

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
