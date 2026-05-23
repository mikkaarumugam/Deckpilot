# MIGRATION — React + FastAPI frontend rewrite

> **Status:** active. Started 2026-05-23. Working on `feature/react-frontend`.
> See [DECISIONS § D-018](DECISIONS.md) for the why.
>
> **This doc is the resume point.** If a Claude session ends mid-migration,
> the next session reads this file to know exactly where to pick up.

## Why we're doing it

[`docs/DECISIONS.md`](DECISIONS.md) § D-018 supersedes D-014 (which deferred this
migration). Short version: the Claude-Design output is polished enough that the
visual-polish-vs-time trade-off flipped — a 10-12h focused rewrite preserves all
existing AI PM signal (eval, ADRs, library awareness, state read-back) while
upgrading the demo-video first-impression.

## What's untouched (the safety net)

- `deckpilot/` — Python package. THE BRAIN. Stays as-is.
  - Parser facade, regex + LLM, action schema, executor, undo, MIDI adapter,
    library reader, state-feedback adapter — all still work.
- `app/dashboard.py` — Streamlit dashboard. Kept as backup / fallback.
- `tests/`, all docs, MIDI mappings — untouched.
- `main` branch — untouched until merge decision at Phase 6.

If the migration is abandoned at any point:
```bash
git checkout main
git branch -D feature/react-frontend
# Streamlit + everything else works exactly as before.
```

## What's being added

- `frontend/` — Vite + React + TypeScript app. Calls the new backend.
- `backend/` — FastAPI server. Thin HTTP wrapper around `deckpilot/`. Imports
  the existing parser / executor / adapters; doesn't reimplement them.
- `design/` — input materials from Claude Design (`pilot.jsx`, `app.jsx`,
  `tweaks-panel.jsx`). Reference, not runtime. Kept for visual diffing.

## Process constraint: MIDI port conflict

`python-rtmidi` is exclusive on the IAC port. Only ONE Python process can
hold IAC Driver Bus 1 at a time. So during the migration:

- Streamlit (`streamlit run app/dashboard.py`) must be **stopped** while the
  new FastAPI backend is running.
- Swap as needed: `pkill -f "streamlit run"` → start FastAPI. To go back to
  Streamlit, stop FastAPI → start Streamlit.

The new FastAPI lazy-opens the MIDI port on first `/execute` request, so
running the backend without sending commands is free.

## Three answers we've already locked in (no re-asking)

1. **Mixxx control library** — `python-rtmidi` → macOS IAC Driver. Wrapped in
   `MidiAdapter` (send) + `MixxxFeedback` (receive).
2. **LLM call** — Claude Haiku 4.5 via `claude -p` subprocess (sync). NOT the
   Anthropic SDK (per D-007 — uses existing Claude Pro subscription). FastAPI
   wraps this in `asyncio.to_thread()` to keep the event loop responsive.
3. **Parser return shape** — `ActionPlan(steps=tuple[TimedAction, ...])`.
   `TimedAction(action: DJAction, at_seconds: float)`. `DJAction` is a frozen
   dataclass union of 11 types (PlayDeck, PauseDeck, SetCrossfader, FadeToDeck,
   LoopDeck, NudgeDeck, SetEQ, SetVolume, HotCue, Sync, LoadTrack).

## The plan — six phases, ~10-12h, with checkpoints

Update each `[ ]` to `[x]` as items complete. Commit at the end of each phase.

### Phase 0 — Setup (30 min) ✅ done at `3cabfe5`
- [x] Kill any running Streamlit process
- [x] Create branch `feature/react-frontend`
- [x] Rename design drop `frontend ui/` → `design/`
- [x] Write this MIGRATION.md
- [x] Write DECISIONS.md § D-018 superseding D-014
- [x] Add migration notice to top of CLAUDE.md
- [x] Commit Phase 0 docs (`3cabfe5`)

### Phase 1 — Vite + design tokens (1h) ✅
- [x] `npm create vite@latest frontend -- --template react-ts` (Vite 8, React 19, TS 6)
- [x] Edit `frontend/index.html`: add Google Fonts links for Geist, Geist Mono,
      Instrument Serif, DM Serif Display, Cormorant Garamond, Newsreader
- [x] Create `frontend/src/styles/theme.css` with the `PILOT_DARK` CSS vars from
      `design/pilot.jsx` lines 29-41 + accent computed via `color-mix()`. Light
      theme deferred — fixed at dark for day 1 per D-018 non-goals.
- [x] Move all 7 keyframes into `theme.css`. Plus the 5 reusable button/chip
      classes (pilot-chip, pilot-btn-primary/glow/kbd, pilot-btn-secondary,
      pilot-icon-btn, pilot-deploy)
- [x] `App.tsx` is a Phase-1 sanity card that renders the warm dark surface,
      coral accent button, Instrument Serif "DeckPilot" headline, and Geist
      Mono code chip — verifies every token resolves
- [x] `npm run dev` boots clean (port 5173, 173ms ready time)
- [x] `npm run build` passes TS + bundles 192KB JS / 4KB CSS
- [x] Commit: `feat(frontend): Vite + TS scaffold + design tokens` (`f2a2411`)

### Phase 2 — Component port (3-4h) ✅
Ported pilot.jsx (1275 lines) into 9 modular TS components + a shared
`types.ts` + the demo-mode `usePilotFlow` hook. Visual parity with the
design canvas verified.

- [x] `frontend/src/types.ts` (shared types: Phase, PlanStepState, DeckState…)
- [x] `frontend/src/components/BPMPulse.tsx` (small, animated dot)
- [x] `frontend/src/components/Chip.tsx` (rounded chip with optional kbd hint)
- [x] `frontend/src/components/PhaseBadge.tsx` (typing/parsing/ready/running/done)
- [x] `frontend/src/components/RunButton.tsx` (morphs by phase)
- [x] `frontend/src/components/PlanStep.tsx` (rail+node timeline item)
- [x] `frontend/src/components/DeckCard.tsx` (deck + BPM + track)
- [x] `frontend/src/components/HistoryItem.tsx` (history row with undo)
- [x] `frontend/src/components/CommandCard.tsx` (hero card)
- [x] `frontend/src/Pilot.tsx` (main shell — composes everything)
- [x] `frontend/src/hooks/usePilotFlow.ts` (demo state machine — replaced by
      real backend wiring in Phase 4)
- [x] All renders match `design/pilot.jsx` visually
- [x] `npm run build` passes: 27 modules, 212KB bundle, no TS errors
- [x] Commit: `feat(frontend): Phase 2 — port pilot.jsx into modular TS components` (`aaca9b2`)

### Phase 3 — FastAPI backend (2-3h) ✅
- [x] `pip install fastapi 'uvicorn[standard]'` into the existing venv
      (no separate backend/pyproject.toml — backend imports from the
      project-root `deckpilot/` package directly)
- [x] `backend/main.py` (FastAPI app + CORS for Vite dev origin + lifespan
      handler that calls `stop_feedback()` on shutdown)
- [x] `backend/services/singletons.py` (lazy LibraryReader / MidiAdapter /
      Executor / MixxxFeedback singletons; all return None on init failure
      so callers can degrade gracefully)
- [x] `backend/models.py` (Pydantic models — TrackPayload, DeckStatePayload,
      ProgressPayload, StateResponse, PlanStepPayload, SuggestionPayload,
      ParseRequest/Response, ExecuteRequest/Response, UndoRequest/Response)
- [x] `backend/services/signatures.py` (`render_action(DJAction)` → (fn,
      detail, t, dMs); `summary_signature(actions)` detects bass-swap
      heuristically; `affects_label(actions)` lists touched decks)
- [x] `backend/routes/parse.py` — POST /parse → regex first, LLM via
      `asyncio.to_thread` if needed. Catches LoadTrack in the plan and
      returns it as a `suggestion` payload (per D-015).
- [x] `backend/routes/execute.py` — POST /execute → reconstructs
      ActionPlan via existing `_payload_to_action`, runs via Executor in
      a thread. Catches `LoadTrackSuggestion` and returns it as success
      with a suggestion payload.
- [x] `backend/routes/state.py` — GET /state → MixxxFeedback snapshot +
      library BPM-match (±0.6 BPM tolerance, same as Streamlit dashboard)
- [x] `backend/routes/undo.py` — POST /undo → `inverse_plan(plan)` then run
- [x] `backend/routes/reset.py` — POST /reset → `reset_plan()` then run
- [x] `uvicorn backend.main:app --port 8000` boots cleanly
- [x] Curl tests pass:
      - GET / → service metadata
      - GET /state → both decks identified with live BPM + library lookup
      - POST /parse "play deck 1" → regex path, ~5ms, valid JSON
      - POST /parse "kill the bass on deck 1" → regex path, valid JSON
- [x] Commit: `feat(backend): Phase 3 — FastAPI wrapping deckpilot/ over HTTP` (`52deaa8`)

### Phase 4 — Wire frontend to backend (1-2h) ✅
Two iterations:
- v1 wired eager parse on every keystroke (LLM included). User noticed it
  was firing Haiku on intermediate drafts — wasteful + confusing.
- v2 = **Pattern C** (regex eager, LLM on Enter). New `ParseRequest.mode`
  field on the backend; `mode="regex"` returns a `no_regex_match` sentinel
  when no rule hits, so the UI can render a hint instead of an error.

- [x] `backend/models.py` + `backend/routes/parse.py` — `ParseRequest.mode`
      with "auto" / "regex" / "llm" values
- [x] `frontend/src/api/client.ts` — typed fetch wrappers for /parse,
      /execute, /state, /undo, /reset
- [x] `frontend/src/hooks/usePilotFlow.ts` — REAL Pattern C state machine:
      regex on each keystroke (debounced 150ms), LLM only on Enter; Enter
      is overloaded as "parse via LLM" OR "run plan" depending on state
- [x] `frontend/src/hooks/useDeckState.ts` — polls GET /state every 250ms
- [x] CommandCard takes a real text input + handles Enter via onSubmit;
      shows "(press ⏎ to ask Haiku)" hint when regex misses (gated to ≥4
      chars to avoid flickering during typing)
- [x] Pilot renders live DeckCards from useDeckState; sources history,
      reset, suggestion handling from usePilotFlow
- [x] LoadTrack suggestions render the SuggestionPanel inside CommandCard;
      Run button can't fire on a suggestion
- [x] Bumped suggestion card font sizes (reasoning 14.5px serif; caveat
      12.5px mono; chips 12px mono) for legibility
- [x] `npm run build` passes: 29 modules, 215KB bundle
- [x] Manual e2e: regex commands fire instantly; LLM commands wait for
      Enter; suggestion card renders correctly with reasoning visible
- [x] Commit: `feat: Phase 4 — wire React UI to FastAPI backend (Pattern C)` (`7de4994`)

### Phase 5 — End-to-end testing + polish ✅
Most of the e2e flow was tested live during Phase 4's Pattern C
iteration. The remaining items here are the polish + edge-case fixes
the user surfaced after seeing the wired-up app:

- [x] Pattern C verified: regex commands fire instantly, LLM commands
      wait for Enter, "press ⏎ to ask Haiku" hint surfaces correctly
- [x] Suggestion card font bumps (reasoning 14.5px serif, caveat
      12.5px mono, BPM/key chips 12px mono) — committed in Phase 4
- [x] Eager parseResult clear on text edit: prevents stale plan from
      ghosting during the 150ms regex debounce window
- [x] `play deck 1` → regex 0ms parse → Enter → deck 1 plays ✓
- [x] `kill the bass on deck 1` → regex → Enter → bass cuts ✓
- [x] `kick into the second deck` → Haiku ~4s → deck 2 plays ✓
- [x] `bass swap into deck 2 over 4 seconds` → 6-step plan renders
      before audio → audio executes ✓
- [x] `queue a daft punk track` → suggestion card with reasoning visible ✓
- [x] Reset → returns Mixxx to neutral ✓
- [x] Deck cards' BPM + track title update live via /state polling ✓
- [x] Visual parity with `design/pilot.jsx` confirmed
- [ ] Commit: `feat(frontend): Phase 5 — eager clear stale state on edit`

### Phase 6 — Document + merge decision (30 min)
- [ ] Update [DECISIONS.md](DECISIONS.md) D-018 status from "in progress" to "shipped"
- [ ] Update [ROADMAP.md](ROADMAP.md) — React migration in Shipped, demo video still pending
- [ ] Update [CLAUDE.md](../CLAUDE.md) file map: add `frontend/` and `backend/` sections
- [ ] Update [ARCHITECTURE.md](ARCHITECTURE.md): new "Frontend / Backend split" section
- [ ] Decide: merge to main now, or keep on branch until demo video records cleanly
- [ ] If merging: `git checkout main && git merge --ff-only feature/react-frontend`
- [ ] If holding: leave branch; demo from `feature/react-frontend`

## Deliberate non-goals for day 1

These are out of scope for the day-1 push. Each is a `+1-3h` follow-up if
desired later, but the demo doesn't need them:

- **WebSocket streaming** of step.done events — replaced with 250ms polling.
- **The Tweaks panel** (`design/tweaks-panel.jsx`) — design-tool theme swapper.
  Cool but not user-facing. Theme is fixed at the design's default (dark + coral).
- **Auto-cycling demo loop** (`usePilotFlow` original behavior) — deleted entirely;
  real user-driven flow replaces it.
- **Queue feature** — present visually in design but mocked as static. Backing
  it with real queued execution is a +1-2h follow-up.

## Resume guide for a fresh Claude session

If the current context window fills up, the next Claude session needs:

1. Read this file (`docs/MIGRATION.md`) first to see overall plan + checkboxes.
2. Read [CLAUDE.md](../CLAUDE.md) for project conventions + working style.
3. Read [docs/DECISIONS.md](DECISIONS.md) § D-018 for the why behind the migration.
4. Check `git status` and `git log --oneline | head -10` to see which phase
   commits have landed.
5. Pick up from the first unchecked `[ ]` in the phase list above.

The phase commits make state visible without re-reading code:
- `Phase 0 docs` → setup done
- `feat(frontend): Vite + TS scaffold + design tokens` → Phase 1 done
- `feat(frontend): port pilot.jsx into modular TS components` → Phase 2 done
- `feat(backend): FastAPI wrapping deckpilot/` → Phase 3 done
- `feat: wire React UI to FastAPI backend` → Phase 4 done
- `test(frontend+backend): full e2e flow verified against Mixxx` → Phase 5 done
- ADR D-018 status flipped to "shipped" → Phase 6 done

## Rollback procedure (if we abandon)

```bash
git checkout main
git branch -D feature/react-frontend
rm -rf frontend backend          # if they were created
# design/ stays — it's reference material the user keeps
# Streamlit dashboard at app/dashboard.py still works
streamlit run app/dashboard.py   # back to v0.3
```

The migration is non-destructive on `main` until Phase 6 merges.
