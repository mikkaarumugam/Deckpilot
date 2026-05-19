"""
Evaluation harness. Runs ~20 natural-language prompts through the parser,
checks each result against an expected DJAction, and reports accuracy + latency.

This is the centrepiece artifact for the portfolio. It demonstrates the
"evaluate your AI like a product feature" mindset.

Wired up in M4.
"""

from __future__ import annotations

# TODO(M4):
#   - Define EVAL_CASES: list[(prompt, expected_action)]
#   - For each: run parser, time it, compare to expected
#   - Print a markdown table: prompt | expected | got | match | latency
#   - Summarize at the end: accuracy %, p50/p95 latency, failure categories
