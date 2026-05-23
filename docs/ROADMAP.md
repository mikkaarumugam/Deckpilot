# ROADMAP

Single source of truth for project status. Updated by humans (or future
Claude) when state changes.

Last updated: **2026-05-23**

## ✅ Shipped

| Milestone | What | Commit |
|---|---|---|
| M0 | Skeleton + repo setup | `de0f9e2` |
| M1 | MIDI proof-of-life via IAC → Mixxx (after VDJ pivot) | `c61cd09` |
| M2 | Full DJAction → MIDI pipeline; 6 atomic actions | `efb1bd1` |
| M3 | Natural-language parser (regex + claude -p) | `900346d` |
| S2 | Multi-action plans + EQ/volume/hotcues/sync — bass swap works | `c86fbec` |
| UI-1 | Streamlit dashboard frontend with 4 presets | `446d164` |
| UI-2 | Visible-before-audible plan + one-click undo | `658b757` |
| UI-3 | Action queue + clear history + reset Mixxx | `7e74759` |
| UX-1 | Status panels stay expanded after execution | `a873afb` |
| Perf-1 | Haiku model pinned (vs default Sonnet/Opus) | `777abae` |
| LLM-1 | Prompt fix for deck-default + loop/EQ vocabulary | `b84ec8c` |
| Perf-2 | 6 new regex rules for common atomic phrasings | `b39d6d6` |
| Eval-1 | 29-case eval + methodology + analysis (`docs/EVAL.md`) | `3b0620c` |
| **Lib-1** | **Library reader — read-only Mixxx SQLite access** | `aa07250` |
| **Lib-2** | **MIDI state read-back: play state + BPM + request handshake** | `e1c3b0e` |
| **Lib-3** | **Library-aware LLM + LoadTrack suggestion card** | `9854fba` |
| **UI-fix** | **Restore Material Symbols font (icon-cascade bug)** | `f86efff` |
| **Reason** | **Surface LLM reasoning on the suggestion card** | `ae3356b` |
| **React-1** | **Vite + React + TS scaffold + design tokens** | `f2a2411` |
| **React-2** | **Port pilot.jsx into modular TS components** | `aaca9b2` |
| **React-3** | **FastAPI backend wrapping deckpilot/ over HTTP** | `52deaa8` |
| **React-4** | **React UI wired to FastAPI (Pattern C: regex eager, LLM on Enter)** | `7de4994` |
| **React-5** | **Clear stale state on text edit + suggestion font polish** | `088092d` |
| **GUI-1** | **MixxxGuiAdapter + auto-load via osascript (D-019 supersedes D-015)** | `fa1c2d6` |
| **Stream-1** | **SSE streaming for LLM parses — plan steps reveal as Haiku generates (D-020)** | `fa1c2d6` |
| **Pos-1** | **Playhead position read-back via MIDI scripted output (substrate for D-021)** | `a1a5327` |
| **Agent-1** | **Demo-scoped Tier 2 agent layer: goal-directed schedules with triggers (D-021)** | `a1a5327` |

Functionally end-to-end working: type or speak (via WhisperType) →
parsed via regex or Haiku → library-aware multi-step plan visible in
the dashboard with live deck-state read-back → executed against Mixxx
via MIDI. One-click undo. Queue of pending commands. Reset state.
Sidebar shows live "Deck N · ▶/⏸ · 121.7 BPM · Daft Punk — Around the
World". Track suggestions surfaced when the LLM picks library content.

**Two dashboards now coexist** in the repo:
- `app/dashboard.py` — Streamlit (the original; still works).
- `frontend/` + `backend/` — React + FastAPI (Pattern C: regex eager,
  LLM on Enter). The polished version, built on `feature/react-frontend`
  per DECISIONS § D-018. Run with: quit Streamlit → `uvicorn
  backend.main:app --port 8000 --reload` + `cd frontend && npm run dev`.

## 🔜 Next session(s) — in priority order

### 1. Demo video (60-90s)
The single most impactful remaining artifact. Screen recording of the
dashboard. Audio through Mac speakers picked up by phone or built-in
mic. Suggested flow:
- `play deck 1` — show regex fast-path (⚡ 0.00s)
- `kill the bass on deck 1` — same path, more interesting verbs
- `find me a chill track around 90 bpm` — surfaces suggestion card
  (library-aware reasoning visible)
- *(user drags suggested track onto deck 2)*
- `bass swap into deck 2 over 4 seconds` — multi-step plan visible,
  fires the 6-step transition

### 2. README polish + GitHub push
Update README to reflect current architecture (library awareness, live
state, suggestion card). Link demo video. Link EVAL.md. Push to
GitHub. Add to portfolio.

### 3. Extend EVAL.md with library-aware cases (~1h)
Current eval: 29 cases on non-library prompts. Add ~10 library cases:
- "queue a daft punk track" → expect LoadTrack with a Daft Punk id
- "find something around X BPM" → expect LoadTrack with BPM-matched id
- "load a chill track" → expect LoadTrack with low-BPM pick
- Edge: empty library → expect decline with reasoning
- Edge: ambiguous criteria → expect either decline or principled pick

### 4. Thread 4: the agent layer (parked)
Now newly substrate-ready thanks to Lib-2 (state read-back). Concepts:
- **Beat-aware scheduling** — "in 8 beats, bass swap into deck 2"
- **Goal-directed planning** — "transition to deck 2 in the next 16 bars"
- **Recovery + re-planning** — track ran out, beat-grid drift

Was the biggest pending direction before Library awareness shipped.
Now even more interesting — Sessions 1-3 give an agent state visibility
+ content choice. The remaining gap is musical-time scheduling +
goal-directed planning.

### 5. UI redesign sketch (deferred; see D-014)
Streamlit ceiling is real. FastAPI + React/Tailwind would deliver
polished animations + pixel-perfect chrome. ~4h migration. Listed
in DECISIONS as P2.

## 🪦 Deferred / explicitly out of scope

| Idea | Why deferred |
|---|---|
| ~~Auto-load tracks onto a Mixxx deck~~ | **No longer deferred** — D-019 (2026-05-23) ships a `MixxxGuiAdapter` that drives Mixxx's library search box via `osascript`, then fires Mixxx's load shortcut. Manual-drag suggestion (D-015) is now the *fallback* for ambiguous matches, not the default. |
| **Mixxx stems** | Stems require Mixxx 2.6+. User has 2.5.6 stable. EQ-based bass swap (D-010) covers the demo. Drop-in upgrade when 2.6 stable lands. |
| **Bundled voice input (Whisper)** | User uses WhisperType locally; dictates into any focused input. No need to ship it. |
| **MCP server** | Nice future option but not portfolio-critical. Mentioned in README "what's next". |
| **Anthropic SDK + prompt caching** | Documented swap path in `llm.py`. Adds metered cost; not needed at single-user scale. |
| **FastAPI + React/Tailwind rewrite** | Streamlit ceiling reached but EVAL.md is higher-leverage. See D-014. ~4h migration when revisited. |
| **VirtualDJ Pro HTTP API** | VDJ is paid/throttled. We pivoted away. |
| **Mobile or web-deployed** | Local-only by design. Portfolio is a desktop demo. |
| **Library navigation hack for auto-load** | MoveTop + N×MoveDown + LoadSelectedTrack works but is fragile to any user click in Mixxx's library pane. Documented as a hidden fallback, not shipped. See D-015. |

## 🐛 Known limitations (will surface in EVAL.md)

- LLM defaults to deck 1 for unspecified deck — can be wrong if user is
  on deck 2.
- Crossfader undo snaps to 0.5, not the precise prior value.
- LoopDeck always uses 8 beats regardless of user's `beats` parameter
  (only one beatloop binding in the Mixxx XML).
- Nudge/HotCue/Sync have no clean undo.
- FadeToDeck assumes the crossfader is at the opposite end before
  fading (no state read-back).
- `claude -p` subprocess spawn dominates latency (~400ms) even for
  fast Haiku inference.
