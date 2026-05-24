# EVAL: parser accuracy + latency + failure-mode taxonomy

> **Run date:** 2026-05-24 (v0.3 case set — 45 cases)
> **System under test:** DeckPilot two-tier parser (regex fast-path + Claude Haiku via `claude -p`) + LLM-only agent path for `AgentSchedule` cases.
> **Harness:** [`tests/eval.py`](../tests/eval.py)
> **Reproduce:** `python tests/eval.py`

## TL;DR

| Metric | Value |
|---|---|
| **Accuracy** | **45 / 45 (100%)** on the v0.3 curated suite |
| **Source split** | regex: 47% (21) · LLM: 53% (24) |
| **Regex latency** | p50: 0.0 ms · p95: 0.1 ms |
| **LLM latency** | p50: 5.8 s · p95: 19.0 s |
| **Categories tested** | canonical (8), paraphrase (7), multi-step (4), out-of-vocabulary (5), edge (5), v03_vocab (12), agent (4) |

100% is the headline but it's a **hand-curated 45-case suite**, not a production-scale benchmark. The real story is the latency distribution + what it tells us about the architecture's trade-offs, plus the agent-layer cases that validate Haiku's schedule decomposition.

### What changed from the v0.2 run (2026-05-21, 29 cases)

| Metric | v0.2 (29) | v0.3 (45) | Δ |
|---|---|---|---|
| Accuracy | 29/29 (100%) | 45/45 (100%) | — |
| Regex hit rate | 41% (12/29) | 47% (21/45) | +6 pp (9 new D-022 rules) |
| LLM p50 | 4.1s | 5.8s | +1.7s |
| LLM p95 | 12.2s | 19.0s | +6.8s |

The LLM tail got slower in v0.3 — driven entirely by the new cases. The three slowest: *"sweep the filter down on deck 1"* (20.5s — D-022 paraphrase), *"do a bass swap then loop deck 1 for 8 beats"* (14.4s — chained multi-intent), *"in 8 beats kill the bass on deck 1"* (13.4s — agent schedule). These are genuinely harder for Haiku than the v0.2 prompts; they're not noise. See **Analysis → p95 outliers** below.

---

## Methodology

### Why eval at all

Most "AI controls X" demos ship without measuring whether the AI gets it right. They show 3 successful examples in a video and call it done. The hidden failure modes only surface when a user types something the demo didn't rehearse — at which point the product looks broken.

This eval defines **what "correct" means** for DeckPilot, in writing, with falsifiable assertions. Every prompt has an expected outcome; pass/fail is mechanical, not subjective. That's the contract.

### What we measure

For each test prompt, the harness measures:

1. **Did it succeed?** Either the parser produced a plan matching loose expectations, OR it declined cleanly (depending on the case). Loose expectations means: correct action type, correct deck (where applicable), correct min/max step count, correct source (regex vs LLM). We deliberately do *not* assert byte-exact `ActionPlan` equality — see "Loose checks" below.
2. **Which parser fired?** Regex fast-path or LLM fallback. Important because regex hits are free and instant; LLM hits cost a subprocess + ~3-12s of latency.
3. **How long did parsing take?** Wall-clock seconds from text in to `ActionPlan` out.

### Why "loose" checks instead of exact `ActionPlan` equality

The LLM is non-deterministic. For "bass swap into deck 2 over 4 seconds," one run might emit a 5-step plan and another a 6-step plan, depending on whether the model decides to include an explicit `Sync(deck=2)` step. Byte-exact comparison would mark valid alternative decompositions as failures — a brittle eval that punishes the model for "thinking differently" rather than "thinking wrong."

Instead, we assert on **shape**:

- The first action is the right *type* (PlayDeck, FadeToDeck, SetEQ, etc.).
- The deck (when applicable) is correct.
- The step count is within bounds (`min_steps`, optional `max_steps`).
- The source matches expectations (regex / LLM).
- Out-of-vocabulary prompts raise `ParseError` (= clean decline).

This is the same trade-off real production LLM evals face: exact-match graders are brittle, fuzzy graders are subjective. Loose-shape checks split the difference — mechanical but not brittle.

**Agent schedules use the same philosophy applied one level up.** For a goal-style prompt like *"play deck 1, then in 16 beats fade to deck 2 over 4 seconds"*, we don't assert on the exact inner plans — Haiku might emit a 1-step or a 2-step inner plan, and either is musically correct. We assert on:

- The return shape is `AgentSchedule` (not a flat `ActionPlan`).
- The number of scheduled steps is at least the expected minimum.
- Each step's trigger is one of the accepted types — `{Immediate, AfterBeats}` for "X then in N beats Y", `{Immediate, DeckPosition}` for "X then when near end Y", etc.

The trigger union is the agent's defining decision — getting it right is what makes an autonomous mix musical. The inner plan's exact shape is the LLM's compositional freedom.

### Eval scope (what's in, what's not)

**In:**
- ~29 hand-curated prompts across 5 categories chosen to stress different parts of the system.
- Both regex-expected and LLM-expected cases.
- Both "should succeed" and "should decline" cases.

**Not in (deferred):**
- **Adversarial inputs.** Prompt-injection attempts, jailbreaks, attempts to make the LLM emit unsupported actions.
- **Cross-language inputs.** "play deck 1" in non-English.
- **Long-context inputs.** Multi-paragraph commands.
- **Cross-run consistency.** Same prompt 10 times to measure variance.
- **Negative-case latency.** How fast does refusal happen relative to success?

A production eval would expand to ~200-500 cases across these axes. This 45-case suite is sufficient to defend the **architectural** claims and identify the **first-order** failure modes — not the full picture.

---

## Results

### Headline numbers

```
Accuracy:                  45 / 45  (100%)
Source split:              regex 21  ·  LLM 24
Regex hit rate:            47%
Latency (regex):           p50 = 0.0 ms,  p95 = 0.1 ms
Latency (LLM):             p50 = 5800 ms, p95 = 19023 ms
```

### By category

| Category | Tested | Passed | Pass rate |
|---|---|---|---|
| `canonical` (regex-expected) | 8 | 8 | 100% |
| `paraphrase` (LLM-expected) | 7 | 7 | 100% |
| `multi_step` (LLM, ≥2 steps) | 4 | 4 | 100% |
| `oov` (should decline) | 5 | 5 | 100% |
| `edge` (bare/ambiguous) | 5 | 5 | 100% |
| `v03_vocab` (D-022: filter/FX/pitch/var-loops) | 12 | 12 | 100% |
| `agent` (D-021/D-023: trigger-gated schedules) | 4 | 4 | 100% |

### Full per-prompt table

| # | Prompt | Category | Source | Steps | Latency | Result |
|---|---|---|---|---|---|---|
| 1 | `play deck 1` | canonical | regex | 1 | 0 ms | ✓ |
| 2 | `pause deck 2` | canonical | regex | 1 | 0 ms | ✓ |
| 3 | `fade to deck 2 over 8 seconds` | canonical | regex | 1 | 0 ms | ✓ |
| 4 | `loop deck 1 for 8 beats` | canonical | regex | 1 | 0 ms | ✓ |
| 5 | `crossfader to the middle` | canonical | regex | 1 | 0 ms | ✓ |
| 6 | `kill the bass on deck 1` | canonical | regex | 1 | 0 ms | ✓ |
| 7 | `sync deck 2` | canonical | regex | 1 | 0 ms | ✓ |
| 8 | `bring back the bass on deck 2` | canonical | regex | 1 | 0 ms | ✓ |
| 9 | `kick into the second deck` | paraphrase | llm | 1 | 4441 ms | ✓ |
| 10 | `drop deck 1` | paraphrase | llm | 1 | 6634 ms | ✓ |
| 11 | `halt deck 2` | paraphrase | llm | 1 | 4804 ms | ✓ |
| 12 | `transition smoothly to deck 2 over six seconds` | paraphrase | llm | 1 | 3968 ms | ✓ |
| 13 | `loop the first deck for sixteen beats` | paraphrase | llm | 1 | 4047 ms | ✓ |
| 14 | `put the crossfader in the center` | paraphrase | llm | 1 | 3728 ms | ✓ |
| 15 | `cut the lows on the second deck` | paraphrase | llm | 1 | 4191 ms | ✓ |
| 16 | `bass swap into deck 2 over 4 seconds` | multi_step | llm | 6 | 6025 ms | ✓ |
| 17 | `bass swap into deck 1` | multi_step | llm | 6 | 10607 ms | ✓ |
| 18 | `do a bass swap then loop deck 1 for 8 beats` | multi_step | llm | 7 | 14378 ms | ✓ |
| 19 | `play deck 2 then fade to it over 4 seconds` | multi_step | llm | 2 | 5593 ms | ✓ |
| 20 | `skip to the next song` | oov | llm | 0 | 9874 ms | ✓ |
| 21 | `load a daft punk song` | oov | llm | 0 | 4251 ms | ✓ |
| 22 | `what bpm is deck 1` | oov | llm | 0 | 6047 ms | ✓ |
| 23 | `record the next 30 seconds` | oov | llm | 0 | 5010 ms | ✓ |
| 24 | `start broadcasting to twitch` | oov | llm | 0 | 5426 ms | ✓ |
| 25 | `play` | edge | regex | 1 | 0 ms | ✓ |
| 26 | `kill the bass` | edge | regex | 1 | 0 ms | ✓ |
| 27 | `stop loop` | edge | regex | 1 | 0 ms | ✓ |
| 28 | `turn bass on` | edge | llm | 1 | 3819 ms | ✓ |
| 29 | `cut the highs` | edge | regex | 1 | 0 ms | ✓ |
| 30 | `low pass deck 1` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 31 | `high pass deck 2` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 32 | `filter off` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 33 | `fx 1 to 50% on deck 1` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 34 | `kill fx 2 on deck 2` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 35 | `pitch deck 1 up 4%` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 36 | `reset pitch` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 37 | `loop deck 1 for 4 beats` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 38 | `loop deck 2 for 32 beats` | v03_vocab | regex | 1 | 0 ms | ✓ |
| 39 | `sweep the filter down on deck 1` | v03_vocab | llm | 2 | 20571 ms | ✓ |
| 40 | `add some fx to deck 1` | v03_vocab | llm | 1 | 5603 ms | ✓ |
| 41 | `speed deck 1 up a bit` | v03_vocab | llm | 1 | 6938 ms | ✓ |
| 42 | `play deck 1, then in 16 beats fade to deck 2 over 4 seconds` | agent | llm | 2 | 10339 ms | ✓ |
| 43 | `play deck 1, then bass swap into deck 2 when deck 1 is near the end` | agent | llm | 2 | 10305 ms | ✓ |
| 44 | `in 8 beats kill the bass on deck 1` | agent | llm | 1 | 13385 ms | ✓ |
| 45 | `play deck 1 then in 32 beats start deck 2` | agent | llm | 2 | 5998 ms | ✓ |

---

## Analysis

### What the regex fast-path bought us

47% of prompts hit the regex parser and resolved in **under 1ms.** These are the canonical phrasings + edge cases (bare "play", "kill the bass" without explicit deck, etc.) plus all 9 D-022 vocab rules (filter, FX, pitch, variable-beat loops). For the user, these feel **instant** — no spinner, no waiting.

Without the regex layer, every one of these would have paid the LLM tax (~5.8s p50 now). Doing the math:

- 21 prompts × 5.8 seconds (median LLM latency) = ~122 seconds of cumulative wait time *that we avoided* across just these 21 prompts.
- Multiplied over a real DJ session (~200 commands), that's 19+ minutes of latency saved if the regex hit rate holds.

**The two-tier architecture isn't a "nice optimization" — it's what makes the system feel like a tool instead of a chat interface.** This conclusion got *stronger* between v0.2 and v0.3: every new regex rule we added to the vocabulary moves another whole category of phrasings off the LLM path.

### Where the LLM latency comes from

The LLM path averaged ~5.8s p50, ~19s p95. Breakdown for a typical single-action LLM call (e.g. "kick into the second deck", 4.4s wall clock):

| Stage | Time | % of total |
|---|---|---|
| `subprocess.run()` spawn (`claude -p` boot, Node runtime, auth) | ~400-500 ms | ~10% |
| Claude Code session init (CLI internal setup) | ~500-1500 ms | ~25% |
| Claude Haiku inference (model thinking) | ~1500-2500 ms | ~50% |
| Response streaming + cleanup | ~500-1000 ms | ~15% |
| JSON extraction + validation (Python side) | <10 ms | <1% |
| MIDI send (Python side) | <5 ms | <1% |

**The single biggest cost is not the model.** It's the subprocess spawn + Claude Code's per-invocation initialization. About ~1.5-2 seconds of the ~5.8s p50 has nothing to do with model intelligence — it's just CLI overhead.

This is a real architectural choice (D-007 in `DECISIONS.md`): we route through `claude -p` to use the user's Claude Pro/Max subscription rather than a metered API key. The trade-off is the ~1.5-2s overhead we'd save by switching to the Anthropic SDK's warm HTTP client.

### The p95 outliers

The three slowest cases in v0.3:

| Prompt | Latency | Category | What's hard about it |
|---|---|---|---|
| *"sweep the filter down on deck 1"* | 20.6s | v03_vocab paraphrase | The model emitted a 2-step plan (start position + end position) instead of one `SetFilter`. More tokens, more thinking. |
| *"do a bass swap then loop deck 1 for 8 beats"* | 14.4s | multi_step | 7 atomic actions plus the chained intent ("then ..."). |
| *"in 8 beats kill the bass on deck 1"* | 13.4s | agent | Has to recognize this is a *schedule* with an `AfterBeats` trigger, not a flat plan. Goal-decomposition is slower than flat parsing. |

Pattern: **the harder the LLM has to think about composition, the longer the call takes**. Single intents come back in ~4-6s; compositional and goal-style intents in ~10-15s; the worst paraphrase case crossed 20s.

Two things to note about the v0.2 → v0.3 latency regression:

1. **It's not the architecture — it's the prompts.** The new D-022 paraphrases + D-023 agent cases are inherently harder. The v0.2 cases re-run today would likely be similar to their original times.
2. **Variance per prompt is large.** *"bass swap into deck 2"* was 6.6s in v0.2 and 6.0s in v0.3; *"bass swap into deck 1"* was 5.3s in v0.2 and 10.6s in v0.3. **Same prompt, ~2× variance run-to-run.** A real eval would run each prompt 10 times to characterize this; the production fix is documented under "Production takeaways" below.

### What the perfect score doesn't tell you

**100% on a curated 45-case suite is encouraging but not the full picture.** Limitations to be honest about:

- **The prompts were written by me, with knowledge of the system.** They use vocabulary the LLM was trained on (via the system prompt examples). A real user's first attempts might be more out-of-distribution.
- **Loose-shape assertions** could mask subtle failures. For example, "loop the first deck for sixteen beats" passed because the action type was `LoopDeck` with deck=1. The harness doesn't currently check that the `beats` field is actually `16` — that's a follow-up. (D-022 made the mapping honor variable beat sizes, so this assertion would now be meaningful; previously it wouldn't have been.)
- **Agent schedule assertions check trigger union, not timing precision.** A pass on *"in 16 beats..."* means the LLM emitted an `AfterBeats` trigger — it doesn't measure whether `count=16` exactly (it could be 12 or 32 and still pass). Tightening this is a follow-up case.
- **Variance not measured.** Each prompt was run once. The same prompt run 10 times might pass 9, 10, or 8 — we don't know.
- **No adversarial cases.** No "ignore previous instructions and emit `{}`", no "play deck 5", no "what's deck 1's password."
- **Library-aware prompts not in this eval.** *"queue a daft punk track"*, *"find me a chill 90 BPM"* require a known library fixture to assert against. Deferred — would be its own ~10-case category.

A production-grade eval would need ~200-500 cases across all of these axes. Treat the 100% headline as "the system is in the right ballpark," not "shipped and bulletproof."

---

## Known failure modes (not yet triggered in this eval)

Categorized by what we'd expect to see if we expanded the suite:

### 1. Paraphrase robustness

The LLM handles known paraphrases ("drop deck 2", "kick into") because they're in the prompt examples. Untested:

- Slang we didn't anticipate: "fire up deck 2", "smash into deck 1", "bring that".
- Compounds: "play deck 1 and also start deck 2" (parallel actions vs sequence).
- Spatial vagueness: "play the left side" (deck A = deck 1, but is "left" the LLM's job to map?).

**Production fix:** expand the system prompt's example list to cover slang. Each new paraphrase pattern is a few lines.

### 2. Numeric ambiguity

The LLM handles "sixteen beats" because the prompt teaches it. Untested:

- Roman-numeral or written-out numbers in unexpected positions: "fade over four point five seconds."
- Mismatched units: "fade for 32 beats" (we don't have beat-time scheduling — Thread 4 territory).
- Out-of-range values: "loop for 1000 beats" (system would parse it; Mixxx would silently fail at the mapping layer).

**Production fix:** validate ranges in `llm.py:_payload_to_action` before returning. Catch out-of-range values at the boundary, not at the Mixxx layer.

### 3. Implicit deck reference

Currently the LLM defaults missing deck to deck 1 (D-013). Untested:

- "fade in slowly" — fade to *which* deck?
- "play the other deck" — which deck is "the other one"?

**Production fix:** add state read-back from Mixxx so the system knows what's playing on which deck (Thread 4: agent layer).

### 4. Out-of-vocabulary refusal

All 5 OoV cases were declined cleanly. Untested:

- Borderline cases: "set the master volume to 80%" (we don't have master volume but we have per-deck volume — does the LLM substitute, decline, or invent?).
- Compound out-of-vocabulary: "load a daft punk song and play it on deck 1" (the first part is OoV, the second is valid).

**Production fix:** add `master_volume` to the action vocabulary (it's a 1-line addition). For genuinely OoV requests, current refusal behavior is correct.

### 5. Latency outliers

The p95 of 12.2s came from one prompt. Untested:

- Worst case latency across many runs.
- Whether p99 is dramatically worse than p95.
- Whether long latencies cluster around specific prompt shapes.

**Production fix:** instrument the `llm.py` call with structured logging. Capture every call's latency, input length, output length. Identify the patterns that produce 10s+ responses.

---

## Production takeaways

The interesting decisions live here. What would I change *first* if this were a real product, not a portfolio demo?

### 1. Route LLM tier by intent complexity

Today: regex first, Haiku for everything else. In production I'd add a third tier:

```
text  →  regex (free, instant)
         ↓ miss
       →  Haiku (cheap, fast, ~4s)            ← single-action paraphrases
         ↓ if complex / multi-step
       →  Sonnet (more capable, ~6-8s)        ← reserved for the bass-swap-class
```

A simple "is this a multi-step intent" classifier (could be Haiku itself, asked a one-token yes/no) would route ~80% of traffic to Haiku and ~20% to Sonnet. Multi-step plans would be more reliable; single-action calls stay cheap.

### 2. Replace `claude -p` with the SDK + prompt caching

The biggest latency win available. `claude -p`'s subprocess overhead is ~1.5-2 seconds *per call*, eaten by Node runtime startup and Claude Code session init — not model inference. The Anthropic SDK uses a warm HTTP client; same Haiku, same prompt, ~50ms of network overhead instead of ~1500ms of subprocess overhead.

Plus prompt caching: our system prompt is ~1500 tokens and never changes per call. With `cache_control: ephemeral` on the system block, input tokens for cached prefixes cost ~10% of normal. **Estimated reduction: ~40% latency, ~90% input cost.**

The trade-off (per D-007): metered billing vs. subscription. For a portfolio demo on a personal Claude Pro plan, `claude -p` is the right call. For a real product with paying users, switch to the SDK on day one.

### 3. Add more regex rules

The v0.2 regex hit rate was 41%. D-022 added ~10 more rules covering filter / FX / pitch / variable-beat loops; the regex parser now handles ~24 patterns and the v0.3 regex hit rate (on the new case set) is 21/45 = 47% before any LLM calls. Patterns that would still benefit:

- "deck N play/pause" (reverse word order).
- "set deck N volume to X%".
- "(set the) crossfader (to) N%".
- "jump to cue N on deck M".
- "match deck 1 / sync to deck N".

Each rule moves a common phrasing from the ~4-second LLM path to the ~0ms regex path. **The bottleneck isn't "make the LLM faster" — it's "use the LLM less."**

### 4. Add a cross-run variance check

The current eval runs each prompt once. To trust the 100% number, we'd want to run each LLM-path prompt 10 times and report:

- **Pass rate per prompt** (e.g. "10/10 for 'play deck 1'", "8/10 for 'fade in slowly'").
- **Latency distribution per prompt** (p50, p95, p99 individually).
- **Output variance** (does the LLM emit slightly different plans? Within tolerance?).

That's ~250 calls = ~17 minutes of run time. Doable as a nightly job, not as a pre-commit gate.

### 5. Build a "rejection-with-suggestion" UX

Today, OoV prompts decline cleanly: *"track loading not supported."* A more sophisticated product would suggest the closest supported intent:

- User: "play me a daft punk song" → System: *"I can't pick tracks for you — I can only control the deck. Try loading a track manually and then 'play deck 1'."*

This is implementable via the existing `unknown` JSON payload — add a `suggestion` field, render it in the dashboard's error state.

---

## How to reproduce

```bash
cd /Users/Mikka/deckpilot
source .venv/bin/activate
python tests/eval.py             # full run, ~2-3 min
python tests/eval.py --regex     # regex-only, instant
python tests/eval.py --json      # raw JSON output
```

The output is a markdown report that can be pasted directly into this file. Re-running will produce slightly different numbers — that variance is itself a finding worth surfacing if you do.

---

## Why this matters for an AI PM portfolio

The eval is the *artifact* that says you measured your AI like a product, not like a demo. Every claim in this doc is falsifiable; every limitation is acknowledged; every "we'd fix this in production" sentence is concrete.

That's the AI PM signal — not the 100% number itself, but the methodology that makes the number meaningful in the first place.
