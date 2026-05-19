"""
Parser facade. Tries regex first (fast, free, deterministic), falls back to the
LLM for anything the regex can't handle.

Wired up in M3.
"""

from __future__ import annotations

# TODO(M3): def parse(text: str) -> DJAction
#   1. try regex.parse(text); return if matched
#   2. else llm.parse(text); return if valid
#   3. else raise ParseError
