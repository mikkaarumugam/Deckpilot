# Parser Evaluation

> 🚧 **Status:** placeholder. The real eval runs in M4 (Sunday afternoon of the build weekend). After running `python tests/eval.py`, the table and failure-mode analysis below will be filled in with real numbers.

## Methodology

We test the parser on ~20 hand-written natural-language commands covering:

- **Canonical commands** — "play deck 1", "pause deck 2".
- **Paraphrase robustness** — "kick off deck one", "stop the first deck", "drop deck 2".
- **Numeric variation** — "fade in 8 seconds" vs. "fade over eight seconds" vs. "fade in 8s".
- **Implicit references** — "fade in" (which deck? the inactive one?).
- **Multi-parameter** — "loop deck 1 for 8 beats", "fade to deck 2 over 10 seconds".
- **Out-of-vocabulary** — "skip to the chorus" (we expect the parser to refuse cleanly).

For each prompt, we measure:

1. **Match** — does the parsed `DJAction` equal the expected one?
2. **Latency** — wall-clock time to parse.
3. **Cost** — Anthropic token usage (input + output).

## Results

| # | Prompt | Expected | Got | Match | Latency |
|---|--------|----------|-----|-------|---------|
| _populated by `tests/eval.py` after M4_ |

## Summary

- **Accuracy:** TBD
- **p50 latency:** TBD
- **p95 latency:** TBD
- **Tokens per call (avg):** TBD

## Failure categories

(To be filled in based on actual failures.)

- **Paraphrase robustness** — does the LLM handle phrasings it wasn't shown in the prompt?
- **Numeric ambiguity** — "fade over 8" — seconds? beats? bars?
- **Implicit deck reference** — "fade in" with no deck specified.
- **Out-of-vocabulary refusal** — does the parser cleanly reject unsupported requests, or does it hallucinate a closest-match action?

## Takeaways for production

(To be filled in after the eval runs. The interesting questions:)

- Where does the regex fast-path actually save latency, and how often does it fire?
- Which failure modes are fixable with a better system prompt vs. requiring a more capable model?
- What's the cost-per-correct-action? At Haiku pricing, what does 1000 commands cost?
- What would a "rejection" UX look like — should the system ask a clarifying question rather than guess?
