# INTERVIEW_NARRATIVE.md

The portfolio storytelling document. Use this before an interview to
remind yourself how to talk about DeckPilot.

## The 60-second pitch

> *"DeckPilot is a natural-language control layer for DJ software. You
> type or speak a high-level command — 'fade to deck 2 over 8 seconds',
> 'bass swap into deck 2', 'loop deck 1 for 8 beats' — and the system
> parses it into a structured plan of MIDI actions, then executes them
> through Mixxx via macOS's virtual MIDI driver. Multi-step transitions
> like the bass swap fire as a coordinated 6-step plan, not as one
> action. The interesting design call is that I don't let the LLM
> control Mixxx directly — it emits one of ten typed actions, and a
> deterministic Python layer executes them. That gives me testability,
> safety, and portability across DJ software. I built it in a
> long weekend as a portfolio piece for AI PM applications."*

That's the answer to *"tell me about a project you've built."* Memorize
the arc; the words can vary.

## The killer demo flow (90 seconds)

Sequence for the demo video. You sit at the laptop with Mixxx open,
two tracks loaded, screen-recording on.

1. **Type:** `play deck 1` — deck plays. Show this hits the regex
   fast-path (`⚡ regex`, `0.00s` parse). *"This is the boring case —
   regex catches the canonical phrasings instantly."*
2. **Type:** `kill the bass on deck 1` — bass cuts. *"Same regex
   path, more interesting verbs."*
3. **Type:** `kick into the second deck` — deck 2 plays. *"Now the
   LLM kicks in for paraphrases the regex can't anticipate."*
4. **Type:** `bass swap into deck 2 over 4 seconds` — multi-step plan
   appears in the table. *"And this is where the architecture pays
   off. The LLM emitted a 6-step plan with timing — pre-cut bass,
   sync, fade, mid-fade swap, restore — that's the real DJ technique.
   Watch the table fill in before the audio fires; that's the
   plan-visible-before-audible UX. No confirmation needed because the
   eyes confirm before the ears."*
5. **Click ↶ Undo** on the bass swap entry — system reverses it.
   *"And of course, one-click undo on anything reversible."*

If you have time for a final flex: **type `do a bass swap then loop
deck 1 for 8 beats`** — the LLM stitches two intents into one plan.

## Q&A — the questions you'll get

### "Why did you build this?"

> *"To prove to myself I could ship an end-to-end AI product, not just
> talk about one. AI PM portfolios are usually RAG chatbots; I wanted
> something different — real-time, creative, with real constraints
> (audio, latency, hardware integration). And honestly, I like DJing.
> The intersection of LLMs and a real-time creative tool seemed
> underexplored."*

### "What's the architecture?"

Walk through the pipeline diagram from `docs/ARCHITECTURE.md`:
```
text → parser (regex|LLM) → ActionPlan → executor → MidiAdapter → IAC → Mixxx
```

Key beats:
- **Structured action vocabulary** — 10 typed dataclasses. The LLM
  can only emit one of these shapes, not arbitrary MIDI.
- **Two-tier parser** — regex for the head of the distribution, LLM
  for the tail.
- **Plan layer** — multi-step transitions are first-class. The bass
  swap is a 6-step ActionPlan, not a special-case action.
- **Adapter pattern** — Mixxx is one backend. Swappable.

### "Why did you pivot from VirtualDJ to Mixxx?"

> *"My first target was VirtualDJ. After ~30 minutes of debugging I
> realized VDJ Home throttles unrecognized MIDI controllers to 10
> minutes per launch — actions silently no-op past that. I pivoted to
> Mixxx, fully open-source, no licensing throttle. The pivot took
> about an hour because the adapter pattern was already in place —
> new mapping file, same Python code. That's the architecture earning
> its keep. The pivot also makes the demo more reproducible — anyone
> can replicate this on Mixxx for free."*

### "Why route through `claude -p` instead of the Anthropic SDK?"

> *"Two reasons. First, it uses my existing Claude Pro subscription
> instead of metered API tokens — zero marginal cost for a portfolio
> demo. Second, it kept the dependency footprint small. The trade-off
> is ~400ms of subprocess spawn overhead per call versus ~50ms for the
> SDK's warm HTTP client, and no prompt caching. For a single-user
> local demo, that's fine. For production scale I'd swap to the SDK —
> the interface is identical, it's a 30-line file change in
> `parser/llm.py`."*

### "Why no confirmation before executing?"

> *"For real-time creative tools, blocking confirmations destroy
> flow. So I replaced confirmation with three things together: the
> parsed plan renders BEFORE the audio fires, so eyes confirm before
> ears; one-click undo on every history entry, so the cost of being
> wrong is bounded by recovery time; and measured accuracy via the
> eval suite, so I've earned the right to act without asking. Most AI
> products lean on confirmation because they didn't do the harder
> work of trust-building. Not asking is the senior move — but you
> have to earn it."*

### "How did you pick the model?"

> *"Haiku. Parsing is a classification task with constrained JSON
> output and a dense system prompt doing the heavy lifting. Smaller,
> faster, cheaper — the right tool for the task. If accuracy drops
> on edge cases, the right move is to route specific failure modes
> to Sonnet, not to upgrade the default. Tiered model use, not
> monolithic. Production AI products almost always end up doing
> exactly this."*

### "Walk me through a failure mode."

> *"The most interesting one: early in the build, the LLM was
> refusing commands like 'turn bass on' with 'deck not specified.'
> Technically correct — the prompt asked for a deck, the user didn't
> provide one — but user-hostile. The fix wasn't code; it was a
> three-line edit to the system prompt: explicit default-to-deck-1
> rule, a vocabulary mapping table for EQ verbs, and a tightened
> refusal threshold. Total time to fix: 4 minutes. No Python changed.
> That's the day-to-day of AI product work — model behavior is
> tunable via prompt design, not via more code."*

### "How would you scale this?"

> *"Three steps. (1) Swap `claude -p` for the Anthropic SDK with
> prompt caching — the system prompt is fixed and cacheable, would
> drop input cost ~90% and shave 100-300ms of latency. (2) Add a
> persistent execution worker so the dashboard can handle multiple
> users — the executor today is in-process and single-threaded.
> (3) For really scaling, lift to a multi-tenant service where each
> session has its own MIDI port and Mixxx instance. None of these
> require architectural changes — the boundaries are already drawn
> right."*

### "What would you build next?"

> *"The biggest pending direction is the agent layer. Today's system
> is a translator — one command in, one plan out. The agent version
> would take goals — 'transition to deck 2 in the next 16 bars' —
> read Mixxx state via MIDI feedback to know the BPM and playhead,
> plan a sequence in musical time, then execute. The architecture
> supports it — ActionPlan already does multi-step; I'd add a state
> read-back module and a planning prompt. The doc for that design is
> in `docs/AGENT_DESIGN.md`."*

### "What does this say about you as a PM?"

> *"Three things I'd want them to take away. (a) I can scope. I cut
> stems, multi-tenant deployment, voice integration, and three other
> features that didn't survive the weekend budget. (b) I think in
> terms of failure modes and recovery, not happy paths. The undo +
> plan visibility + eval doc are about earning trust, not adding
> features. (c) I can pivot under fire. Two major rewrites in the
> same weekend — VDJ → Mixxx, SDK → claude-p — both shipped because
> the boundaries were drawn right."*

## The senior-PM lines worth memorizing

These are sentences I drafted with Claude during the build that work
well in interviews:

> *"Confirmation is the polite-but-lazy way to handle uncertainty.
> The interesting work is reducing uncertainty and bounding cost-of-
> error. Asking for permission is what you do when you've given up
> on doing those other things."*

> *"The eval doc is the trust contract. If accuracy is high enough,
> we've earned the right to act without confirmation. If not, we
> can't. The measurement is the permission."*

> *"Prompt tokens substitute for model capacity. A more specific
> prompt lets you use a smaller, faster, cheaper model. The lever a
> production AI PM actually controls is the prompt, not the model."*

> *"The architecture choices that matter most are the ones that let
> you renegotiate later. The adapter pattern survived two major
> pivots in one weekend — that's worth more than perfect design you
> can't change."*

## The portfolio writeup (for the README and resume)

Headline: **"Natural-language control for DJ software via virtual MIDI
+ LLM. Built in one weekend."**

Three-bullet summary:

- **Architecture.** Structured action vocabulary (10 typed actions),
  two-tier parser (regex + Claude Haiku via CLI), multi-step plan
  layer, adapter pattern over MIDI.
- **Trust-without-confirmation UX.** Parsed plan renders before audio
  fires; one-click undo on every action; the eval doc defends the
  no-confirmation choice with numbers.
- **Pivoted twice under fire.** VirtualDJ → Mixxx (after discovering
  VDJ Home's 10-minute MIDI throttle); Anthropic SDK → `claude -p`
  CLI (to use existing subscription, no metered API cost). Both
  swaps took under an hour because the architecture was designed for
  it.

## Failure modes to OWN, not hide

If asked about weaknesses, lead with these — it shows you measured:

- LLM defaults to deck 1 when deck isn't specified. Wrong if user is
  on deck 2. Fixable with state read-back (deferred to agent layer).
- Crossfader undo snaps to 0.5, doesn't restore precise prior value
  — would require state snapshotting, deliberately deferred.
- LoopDeck always uses 8 beats regardless of the parsed `beats`
  parameter (only one beatloop binding shipped). Acknowledged limit.
- Multi-step plans block the executor (a 4-second fade blocks for 4
  seconds). Fine for single-user CLI; would need threading for
  concurrent use.

**Knowing your product's limits cold = senior signal.**
