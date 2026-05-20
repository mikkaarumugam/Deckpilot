# ROADMAP

Single source of truth for project status. Updated by humans (or future
Claude) when state changes.

Last updated: **2026-05-20**

## ✅ Shipped (12 commits on `main`)

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

Functionally end-to-end working: type or speak (via WhisperType) →
parsed via regex or Haiku → coordinated multi-step plan visible in
dashboard → executed against Mixxx via MIDI. One-click undo. Queue
of pending commands. Reset state.

## 🔜 Next session(s) — in priority order

### 1. UI redesign sketch (~30 min discussion, then 1-2h build)
Current Streamlit dashboard grew organically and now feels cramped.
Options to consider:
- **2-column layout** — input + queue on left, status + history on right
- **Tabs** — Live / Queue / History
- **Single-column with stronger visual hierarchy** — bigger input as
  hero, presets de-emphasized, history collapsed by default
- **Move off Streamlit** to FastAPI + HTML/JS (2-3h migration, full
  design freedom)

User flagged this — `agent` to come back with 2-3 mockups for comparison.

### 2. Thread 4: the agent question
Where today's work compounds. Concepts to expand:
- **Beat-aware scheduling** — "in 8 beats, bass swap into deck 2" requires
  knowing where the beat is. Either: read Mixxx state via MIDI feedback,
  or use Mixxx's HTTP API, or use BPM + clock arithmetic from a known
  anchor.
- **State read-back** — currently fire-and-forget. Agent needs to know
  what's playing, where in the track, what the BPM is, what the
  crossfader is at.
- **Goal-directed planning** — instead of "do a bass swap into deck 2",
  the user says "transition to deck 2 in the next 16 bars" and the system
  plans the moves itself.
- **Recovery and re-planning** — if something fails mid-plan (track ran
  out, beat-grid drift), agent should adapt.

This is the conceptually richest thread. Deserves fresh energy and
probably its own session.

### 3. EVAL.md (~2h, the AI PM money-shot)
The single highest-leverage artifact for the portfolio. Plan:
- Hand-write ~30 NL prompts covering: canonical commands, paraphrases,
  multi-step plans, intentional out-of-vocabulary
- Hand-label each with expected ActionPlan
- Run the parser on each, measure accuracy + parse latency + (regex vs LLM) source
- Categorize failures: paraphrase robustness, numeric ambiguity,
  implicit deck reference, out-of-vocabulary refusal
- Write the prose around the numbers explaining what was measured and
  what we'd do about each failure mode

### 4. Demo video (60-90s)
After UI redesign + eval. Screen recording of the dashboard. Audio
through Mac speakers picked up by phone or built-in mic. Run 4-5
commands ending with "do a bass swap then loop deck 1 for 8 beats"
as the wow moment.

### 5. README polish + GitHub push
Final pass on README pitch, link demo video, link EVAL.md. Push to
GitHub. Add to portfolio.

## 🪦 Deferred / explicitly out of scope

| Idea | Why deferred |
|---|---|
| **Mixxx stems** | Stems require Mixxx 2.6+. User has 2.5.6 stable. EQ-based bass swap (D-010) covers the demo. Drop-in upgrade when 2.6 stable lands. |
| **Bundled voice input (Whisper)** | User uses WhisperType locally; dictates into any focused input. No need to ship it. |
| **MCP server** | Nice future option but not portfolio-critical. Mentioned in README "what's next". |
| **State read-back from Mixxx** | Required for Thread 4. Will design once we start that thread. |
| **Anthropic SDK + prompt caching** | Documented swap path in `llm.py`. Adds metered cost; not needed at single-user scale. |
| **VirtualDJ Pro HTTP API** | VDJ is paid/throttled. We pivoted away. |
| **Mobile or web-deployed** | Local-only by design. Portfolio is a desktop demo. |

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
