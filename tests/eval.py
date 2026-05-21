"""
DeckPilot evaluation harness.

Runs ~30 hand-curated prompts through the parser, measures accuracy +
latency + source-path distribution, and prints a markdown-formatted
report suitable for pasting into docs/EVAL.md.

Usage:
    python tests/eval.py             # full run (~2 min, ~25 LLM calls)
    python tests/eval.py --regex     # only regex-expected cases (instant)
    python tests/eval.py --json      # emit raw JSON, no markdown

Why this isn't part of pytest:
- LLM calls take ~1s each; ~25 of them per full run = ~2 min wall clock.
- LLM responses are non-deterministic; a flaky pytest gate is worse than
  no gate.
- This script is an artifact you run periodically (before a release,
  before recording a demo) and paste results into EVAL.md. The regex
  tests in test_parser.py are the deterministic CI gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from deckpilot.core.actions import (
    DJAction,
    FadeToDeck,
    HotCue,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetVolume,
    Sync,
)
from deckpilot.core.parser import parse
from deckpilot.core.parser import regex as regex_parser
from deckpilot.core.parser.errors import ParseError


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass
class Case:
    """One eval prompt with loose expectations.

    We use 'loose' checks rather than ActionPlan equality because LLM
    multi-step plans aren't byte-deterministic — the bass swap might
    emit 5 or 6 steps depending on the run. We assert on shape, not
    on exact text. See docs/EVAL.md § Methodology for the trade-off.
    """
    prompt: str
    category: str
    # Loose expectations:
    expected_first_action_type: Optional[type] = None
    expected_deck: Optional[int] = None
    expected_min_steps: int = 1
    expected_max_steps: Optional[int] = None
    expected_source: Optional[str] = None        # "regex" | "llm" | None (don't check)
    expected_decline: bool = False               # True = parser should raise ParseError


CASES: list[Case] = [
    # === Canonical (regex fast-path expected) ===
    Case("play deck 1", "canonical", PlayDeck, 1, expected_source="regex"),
    Case("pause deck 2", "canonical", PauseDeck, 2, expected_source="regex"),
    Case("fade to deck 2 over 8 seconds", "canonical", FadeToDeck, 2, expected_source="regex"),
    Case("loop deck 1 for 8 beats", "canonical", LoopDeck, 1, expected_source="regex"),
    Case("crossfader to the middle", "canonical", SetCrossfader, expected_source="regex"),
    Case("kill the bass on deck 1", "canonical", SetEQ, 1, expected_source="regex"),
    Case("sync deck 2", "canonical", Sync, 2, expected_source="regex"),
    Case("bring back the bass on deck 2", "canonical", SetEQ, 2, expected_source="regex"),

    # === Paraphrases (LLM path expected) ===
    Case("kick into the second deck", "paraphrase", PlayDeck, 2, expected_source="llm"),
    Case("drop deck 1", "paraphrase", PlayDeck, 1, expected_source="llm"),
    Case("halt deck 2", "paraphrase", PauseDeck, 2, expected_source="llm"),
    Case("transition smoothly to deck 2 over six seconds", "paraphrase",
         FadeToDeck, 2, expected_source="llm"),
    Case("loop the first deck for sixteen beats", "paraphrase", LoopDeck, 1,
         expected_source="llm"),
    Case("put the crossfader in the center", "paraphrase", SetCrossfader,
         expected_source="llm"),
    Case("cut the lows on the second deck", "paraphrase", SetEQ, 2),

    # === Multi-step (LLM plan with multiple actions) ===
    Case("bass swap into deck 2 over 4 seconds", "multi_step", expected_source="llm",
         expected_min_steps=4),
    Case("bass swap into deck 1", "multi_step", expected_source="llm",
         expected_min_steps=4),
    Case("do a bass swap then loop deck 1 for 8 beats", "multi_step",
         expected_source="llm", expected_min_steps=5),
    Case("play deck 2 then fade to it over 4 seconds", "multi_step",
         expected_source="llm", expected_min_steps=2),

    # === Out-of-vocabulary (should decline cleanly, not hallucinate) ===
    Case("skip to the next song", "oov", expected_decline=True),
    Case("load a daft punk song", "oov", expected_decline=True),
    Case("what bpm is deck 1", "oov", expected_decline=True),
    Case("record the next 30 seconds", "oov", expected_decline=True),
    Case("start broadcasting to twitch", "oov", expected_decline=True),

    # === Edge cases ===
    Case("play", "edge", PlayDeck, 1, expected_source="regex"),
    Case("kill the bass", "edge", SetEQ, 1, expected_source="regex"),
    Case("stop loop", "edge", LoopDeck, 1, expected_source="regex"),
    Case("turn bass on", "edge", SetEQ, 1),
    Case("cut the highs", "edge", SetEQ, 1, expected_source="regex"),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class Result:
    case: Case
    success: bool
    actual_first_action: Optional[DJAction] = None
    actual_step_count: int = 0
    actual_source: str = "?"
    latency_seconds: float = 0.0
    error: Optional[str] = None
    failure_reason: Optional[str] = None


def _detect_source(prompt: str) -> str:
    """Did the regex parser match this prompt, or did it fall through to the LLM?"""
    return "regex" if regex_parser.parse(prompt) is not None else "llm"


def _run_case(case: Case) -> Result:
    start = time.monotonic()
    actual = None
    err: Optional[str] = None
    try:
        actual = parse(case.prompt)
    except ParseError as exc:
        err = str(exc)
    latency = time.monotonic() - start
    source = _detect_source(case.prompt)

    # Expected to be declined
    if case.expected_decline:
        if err is not None:
            return Result(case, True, None, 0, source, latency, err)
        return Result(case, False, actual.steps[0].action if actual else None,
                      len(actual.steps) if actual else 0, source, latency,
                      failure_reason=f"expected decline; got plan with {len(actual.steps) if actual else 0} steps")

    # Expected to succeed but errored
    if err is not None:
        return Result(case, False, None, 0, source, latency, err,
                      failure_reason=f"unexpected decline: {err}")

    assert actual is not None
    first = actual.steps[0].action

    # Source check (when specified)
    if case.expected_source is not None and source != case.expected_source:
        return Result(case, False, first, len(actual.steps), source, latency,
                      failure_reason=f"source mismatch: expected {case.expected_source}, got {source}")

    # First-action-type check
    if case.expected_first_action_type is not None and not isinstance(first, case.expected_first_action_type):
        return Result(case, False, first, len(actual.steps), source, latency,
                      failure_reason=f"first action: expected {case.expected_first_action_type.__name__}, got {type(first).__name__}")

    # Deck check (where the first action has a deck attribute)
    if case.expected_deck is not None and hasattr(first, "deck"):
        actual_deck = getattr(first, "deck")
        if actual_deck != case.expected_deck:
            return Result(case, False, first, len(actual.steps), source, latency,
                          failure_reason=f"deck mismatch: expected {case.expected_deck}, got {actual_deck}")

    # Step-count bounds
    if len(actual.steps) < case.expected_min_steps:
        return Result(case, False, first, len(actual.steps), source, latency,
                      failure_reason=f"too few steps: {len(actual.steps)} < {case.expected_min_steps}")
    if case.expected_max_steps is not None and len(actual.steps) > case.expected_max_steps:
        return Result(case, False, first, len(actual.steps), source, latency,
                      failure_reason=f"too many steps: {len(actual.steps)} > {case.expected_max_steps}")

    return Result(case, True, first, len(actual.steps), source, latency)


def run_all(regex_only: bool = False) -> list[Result]:
    cases = CASES
    if regex_only:
        cases = [c for c in CASES if c.expected_source == "regex" or _detect_source(c.prompt) == "regex"]
    results: list[Result] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.prompt!r}", end="  ", flush=True)
        r = _run_case(case)
        results.append(r)
        if r.success:
            print(f"✓  ({r.latency_seconds*1000:.0f}ms, {r.actual_source})")
        else:
            print(f"✗  {r.failure_reason}")
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _summarize(results: list[Result]) -> dict:
    total = len(results)
    passes = sum(1 for r in results if r.success)
    by_category: dict[str, dict] = {}
    for r in results:
        c = r.case.category
        by_category.setdefault(c, {"total": 0, "passes": 0})
        by_category[c]["total"] += 1
        if r.success:
            by_category[c]["passes"] += 1

    regex_latencies = [r.latency_seconds for r in results if r.actual_source == "regex"]
    llm_latencies = [r.latency_seconds for r in results if r.actual_source == "llm"]

    def pct(x: list[float], p: int) -> float:
        if not x:
            return 0.0
        return statistics.quantiles(x, n=100)[p - 1] if len(x) >= 2 else x[0]

    return {
        "total": total,
        "passes": passes,
        "accuracy": passes / total if total else 0.0,
        "by_category": by_category,
        "regex_count": len(regex_latencies),
        "llm_count": len(llm_latencies),
        "regex_p50": statistics.median(regex_latencies) if regex_latencies else 0.0,
        "regex_p95": pct(regex_latencies, 95),
        "llm_p50": statistics.median(llm_latencies) if llm_latencies else 0.0,
        "llm_p95": pct(llm_latencies, 95),
    }


def print_markdown_report(results: list[Result]) -> None:
    s = _summarize(results)
    out: list[str] = []
    out.append(f"## Summary\n")
    out.append(f"- **Total:** {s['total']} prompts")
    out.append(f"- **Accuracy:** {s['passes']}/{s['total']} ({s['accuracy']*100:.0f}%)")
    out.append(f"- **Source split:** regex {s['regex_count']} ({s['regex_count']/s['total']*100:.0f}%) · "
               f"LLM {s['llm_count']} ({s['llm_count']/s['total']*100:.0f}%)")
    out.append(f"- **Latency (regex):** p50 {s['regex_p50']*1000:.1f}ms · p95 {s['regex_p95']*1000:.1f}ms")
    out.append(f"- **Latency (LLM):** p50 {s['llm_p50']*1000:.0f}ms · p95 {s['llm_p95']*1000:.0f}ms")
    out.append("")

    out.append("## By category\n")
    out.append("| Category | Pass rate |")
    out.append("|---|---|")
    for cat, d in s["by_category"].items():
        out.append(f"| `{cat}` | {d['passes']}/{d['total']} ({d['passes']/d['total']*100:.0f}%) |")
    out.append("")

    out.append("## Per-prompt results\n")
    out.append("| # | Prompt | Category | Source | Steps | Latency | Result |")
    out.append("|---|---|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        status = "✓" if r.success else "✗"
        latency = f"{r.latency_seconds*1000:.0f}ms"
        prompt = r.case.prompt.replace("|", "\\|")
        out.append(f"| {i} | `{prompt}` | {r.case.category} | {r.actual_source} | {r.actual_step_count} | {latency} | {status} |")
    out.append("")

    failures = [r for r in results if not r.success]
    if failures:
        out.append("## Failures\n")
        for r in failures:
            out.append(f"- `{r.case.prompt}` ({r.case.category}) — {r.failure_reason}")
        out.append("")

    print("\n".join(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regex", action="store_true", help="only run regex-expected cases")
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of markdown")
    args = ap.parse_args()

    print(f"Running {sum(1 for c in CASES if not args.regex or c.expected_source == 'regex')} eval cases...\n")
    results = run_all(regex_only=args.regex)
    print()

    if args.json:
        out = [{
            "prompt": r.case.prompt,
            "category": r.case.category,
            "success": r.success,
            "source": r.actual_source,
            "step_count": r.actual_step_count,
            "latency_ms": r.latency_seconds * 1000,
            "failure_reason": r.failure_reason,
        } for r in results]
        print(json.dumps(out, indent=2))
    else:
        print_markdown_report(results)

    s = _summarize(results)
    return 0 if s["passes"] == s["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
