"""
Streaming LLM parser — mirror of llm.py that emits plan steps as
Haiku generates them, instead of waiting for the full response.

Uses `claude -p --output-format=stream-json` which emits JSONL events
to stdout: one JSON object per line. We filter to `text_delta` events
inside `content_block_delta` (ignoring `thinking_delta` events from
Haiku's extended-thinking pass), feed the text to a tolerant
brace-counting parser, and yield each plan step as it becomes fully
parseable.

This module is intentionally separate from llm.py (the synchronous
path) so the non-streaming caller (CLI, eval harness, tests) is
unchanged. The streaming path is opt-in via the new FastAPI route
/parse/stream.

See DECISIONS § D-019 for the broader UX context (latency reduction
without an API-key swap).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import TYPE_CHECKING, Any, AsyncIterator

from .errors import ParseError
from .llm import (
    CLAUDE_BINARY,
    LLM_MODEL,
    TIMEOUT_SECONDS,
    LLMParseError,
    _payload_to_plan,
    _payload_to_schedule,
    build_system_prompt,
    payload_has_schedule,
)

if TYPE_CHECKING:
    from deckpilot.adapters.midi_feedback import MixxxState
    from deckpilot.library import LibraryReader


class _StepExtractor:
    """Tolerant streaming extractor for the plan-step objects inside
    the LLM's emitted `"plan": [...]` array.

    Scans incoming text character-by-character, tracking JSON brace
    depth (with string/escape awareness). Each time depth returns to 0
    at a top-level `}` inside the plan array, we've got a complete step
    object — slice it out and `json.loads` it.

    Not a full JSON parser. It assumes the LLM's output looks roughly
    like `{ "plan": [ {...}, {...} ], ... }` with steps as simple
    nested objects. Which is what our prompt guarantees.
    """

    def __init__(self) -> None:
        self.buffer: str = ""
        self.plan_started: bool = False
        self.cursor: int = 0
        self.depth: int = 0  # depth INSIDE the plan array (0 = at array level)
        self.in_string: bool = False
        self.escape: bool = False
        self.current_step_start: int = -1

    def feed(self, text: str) -> list[dict[str, Any]]:
        """Append new text; return any newly-complete plan-step objects."""
        self.buffer += text
        emitted: list[dict[str, Any]] = []

        if not self.plan_started:
            # Look for the start of the plan array. The model emits
            # something like `{"plan": [ ...` somewhere near the top.
            idx = self.buffer.find('"plan"')
            if idx < 0:
                return emitted
            bracket = self.buffer.find("[", idx)
            if bracket < 0:
                return emitted
            self.plan_started = True
            self.cursor = bracket + 1
            self.depth = 0

        while self.cursor < len(self.buffer):
            c = self.buffer[self.cursor]

            if self.in_string:
                if self.escape:
                    self.escape = False
                elif c == "\\":
                    self.escape = True
                elif c == '"':
                    self.in_string = False
            else:
                if c == '"':
                    self.in_string = True
                elif c == "{":
                    if self.depth == 0:
                        self.current_step_start = self.cursor
                    self.depth += 1
                elif c == "}":
                    self.depth -= 1
                    if self.depth == 0 and self.current_step_start >= 0:
                        step_text = self.buffer[self.current_step_start : self.cursor + 1]
                        try:
                            emitted.append(json.loads(step_text))
                        except json.JSONDecodeError:
                            # Shouldn't happen if brace tracking is right
                            # — but if the LLM emitted something we can't
                            # parse, just skip and let final parse catch it.
                            pass
                        self.current_step_start = -1
                # ']' at depth 0 signals end of plan array — fine to
                # keep scanning; nothing more to emit.
            self.cursor += 1

        return emitted


async def stream_parse_llm(
    text: str,
    *,
    library: "LibraryReader | None" = None,
    deck_state: "MixxxState | None" = None,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator. Yields events in this order:

      {"type": "started"}
      {"type": "step", "index": N, "step": <raw step dict>}    (0+ times)
      {"type": "complete", "plan": <ActionPlan>}               (on success)
      {"type": "error", "message": str}                        (on failure)

    The 'step' events carry the *raw* dict the model emitted (matching
    what _payload_to_action consumes). Caller is responsible for
    converting to wire format. The 'complete' event carries the fully-
    parsed ActionPlan, validated end-to-end.
    """
    if shutil.which(CLAUDE_BINARY) is None:
        yield {
            "type": "error",
            "message": f"{CLAUDE_BINARY!r} CLI not found on PATH. Install Claude Code.",
        }
        return

    full_prompt = (
        build_system_prompt(library=library, deck_state=deck_state)
        + "\n\nUser command:\n"
        + text
        + "\n\nReturn ONLY the JSON object now."
    )

    yield {"type": "started"}

    proc = await asyncio.create_subprocess_exec(
        CLAUDE_BINARY,
        "-p",
        "--model",
        model or LLM_MODEL,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",  # required by claude -p when using stream-json
        full_prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    extractor = _StepExtractor()
    full_text = ""
    emitted_count = 0

    try:
        assert proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                proc.kill()
                yield {
                    "type": "error",
                    "message": f"claude -p timed out after {TIMEOUT_SECONDS}s",
                }
                return

            if not line:
                break  # EOF

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip non-JSON noise

            # We care about content_block_delta events with text_delta.
            # Ignore thinking_delta (Haiku's chain-of-thought, not the
            # structured output we want to stream).
            if event.get("type") != "stream_event":
                continue
            inner = event.get("event", {})
            if inner.get("type") != "content_block_delta":
                continue
            delta = inner.get("delta", {})
            if delta.get("type") != "text_delta":
                continue
            chunk = delta.get("text", "")
            if not chunk:
                continue

            full_text += chunk
            for step in extractor.feed(chunk):
                yield {"type": "step", "index": emitted_count, "step": step}
                emitted_count += 1

        await proc.wait()

        if proc.returncode != 0:
            stderr_bytes = await proc.stderr.read() if proc.stderr else b""
            yield {
                "type": "error",
                "message": (
                    f"claude -p exited with status {proc.returncode}. "
                    f"stderr: {stderr_bytes.decode(errors='replace')[:500]!r}"
                ),
            }
            return

        # End of stream — do the final, strict parse on the full text
        # so the caller gets a validated ActionPlan / AgentSchedule
        # with the same guarantees as the synchronous path.
        try:
            payload = _extract_json(full_text)
            if payload_has_schedule(payload):
                schedule = _payload_to_schedule(payload, original_text=text)
                yield {"type": "complete", "schedule": schedule}
                return
            plan = _payload_to_plan(payload, original_text=text)
        except ParseError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        yield {"type": "complete", "plan": plan}

    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


def _extract_json(raw: str) -> dict[str, Any]:
    """Same logic as llm._extract_json. Duplicated here to avoid an
    import cycle since llm.py doesn't need the streaming side."""
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMParseError(f"no JSON object found in streamed LLM output: {raw!r}")
    candidate = raw[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMParseError(
            f"streamed LLM output not valid JSON. candidate={candidate!r}"
        ) from exc
