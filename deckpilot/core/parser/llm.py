"""
LLM-based parser. Calls Claude with the action schema as a system prompt and
asks for JSON matching one of the DJAction dataclasses.

Why this design (worth understanding for the AI PM angle):
- We give the LLM a tight, enumerated set of outputs (6 actions). It can't ask
  for things we don't support.
- We validate the JSON against the dataclass before returning. If validation
  fails, we treat it as a parse error rather than crashing the system.
- Latency: ~1-3s per call to Haiku. That's fine for typed commands but is the
  reason we keep a regex fast-path for common cases.
"""

from __future__ import annotations

# TODO(M3): implement parse(text) -> DJAction
#   - Build a system prompt describing the schema in docs/ARCHITECTURE.md
#   - Use claude-haiku-4-5-20251001 for speed
#   - Parse the returned JSON into a DJAction dataclass
#   - Raise ParseError on invalid JSON or out-of-vocabulary actions
