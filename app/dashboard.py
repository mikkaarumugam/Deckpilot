"""
DeckPilot dashboard — Streamlit frontend for the DJ control system.

What this gives you that the CLI doesn't:
  - A focused text input you can type or dictate into.
  - A visualization of the parsed plan BEFORE execution — recruiters
    watching a 60-second portfolio video can see the AI's structured
    output, which is the whole point of the project.
  - A running history of every command, what source parsed it
    (regex vs LLM), and how long parsing + execution took.
  - Four preset buttons that double as a demo-video script and a
    one-click regression test after code changes.

Run:
    streamlit run app/dashboard.py
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

import streamlit as st

from deckpilot.adapters.midi import MidiAdapter
from deckpilot.core.actions import ActionPlan
from deckpilot.core.executor import Executor
from deckpilot.core.parser import parse as facade_parse
from deckpilot.core.parser import regex as regex_parser
from deckpilot.core.parser.errors import ParseError


# Curated presets: each exercises a different path through the system.
# 1. Regex fast-path (instant).
# 2. Single-action LLM call (~1-2s).
# 3. Multi-step plan (~1-2s parse, then 4s execution — the "wow" moment).
# 4. LLM stitches two intents into one ordered plan (the "agentic" demo).
PRESETS = [
    "play deck 1",
    "kill the bass on deck 1",
    "bass swap into deck 2 over 4 seconds",
    "do a bass swap then loop deck 1 for 8 beats",
]


# ---------------------------------------------------------------------------
# State + adapter setup
# ---------------------------------------------------------------------------

def get_executor() -> Executor:
    """Lazily create one MidiAdapter + Executor and keep them across reruns.

    Streamlit re-executes the whole script on every interaction. We stash
    the executor in session_state so we don't reopen the MIDI port a hundred
    times per session.
    """
    if "executor" not in st.session_state:
        adapter = MidiAdapter()
        st.session_state.executor = Executor(adapter)
        st.session_state.port_name = adapter.port_name
    return st.session_state.executor


def init_state() -> None:
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("last_input", None)
    st.session_state.setdefault("last_plan", None)
    st.session_state.setdefault("last_source", None)
    st.session_state.setdefault("last_parse_latency", 0.0)
    st.session_state.setdefault("last_exec_latency", 0.0)
    st.session_state.setdefault("last_error", None)


# ---------------------------------------------------------------------------
# Parsing + execution
# ---------------------------------------------------------------------------

def parse_with_metadata(text: str) -> tuple[ActionPlan, str, float]:
    """
    Parse and return (plan, source, parse_seconds).

    We deliberately call regex first ourselves (instead of letting the facade
    do it transparently) so we can record WHICH parser actually fired. That
    metadata is what makes the dashboard interesting — users see when
    something hits the fast-path vs the LLM.
    """
    start = time.monotonic()
    plan = regex_parser.parse(text)
    if plan is not None:
        return plan, "regex", time.monotonic() - start

    # Regex missed → facade falls through to LLM. (We could call llm.parse()
    # directly here, but using the facade keeps a single source of truth.)
    plan = facade_parse(text)
    return plan, "llm", time.monotonic() - start


def handle_command(text: str) -> None:
    """Parse, execute, and update history. Called by both the form and presets."""
    text = text.strip()
    if not text:
        return

    st.session_state.last_input = text

    try:
        plan, source, parse_latency = parse_with_metadata(text)
    except ParseError as exc:
        st.session_state.last_plan = None
        st.session_state.last_error = str(exc)
        st.session_state.history.insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "text": text,
            "summary": "declined",
            "status": "✗",
            "detail": str(exc),
        })
        return

    st.session_state.last_plan = plan
    st.session_state.last_source = source
    st.session_state.last_parse_latency = parse_latency
    st.session_state.last_error = None

    # Block while executing — Streamlit's spinner shows top-right.
    executor = get_executor()
    exec_start = time.monotonic()
    with st.spinner(f"Executing plan ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''})..."):
        executor.run_plan(plan)
    st.session_state.last_exec_latency = time.monotonic() - exec_start

    summary = (
        f"{len(plan.steps)} steps"
        if len(plan.steps) > 1
        else _describe_action(plan.steps[0].action)
    )
    st.session_state.history.insert(0, {
        "time": time.strftime("%H:%M:%S"),
        "text": text,
        "summary": summary,
        "status": "✓",
        "detail": f"{source}, {parse_latency:.2f}s parse + {st.session_state.last_exec_latency:.2f}s exec",
    })


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _describe_action(action: Any) -> str:
    """Human-readable single-line summary of a DJAction."""
    cls = type(action).__name__
    fields = ", ".join(f"{k}={v}" for k, v in asdict(action).items())
    return f"{cls}({fields})"


def render_plan_panel() -> None:
    if st.session_state.last_error is not None:
        st.error(f"Could not parse: {st.session_state.last_error}")
        return

    if st.session_state.last_plan is None:
        st.info("Submit a command above. The parsed plan will appear here.")
        return

    plan: ActionPlan = st.session_state.last_plan

    source_label = (
        "🤖 LLM" if st.session_state.last_source == "llm" else "⚡ regex"
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**Input:** `{st.session_state.last_input}`")
    with col2:
        st.markdown(
            f"**Source:** {source_label} · "
            f"`{st.session_state.last_parse_latency:.2f}s`"
        )

    rows = [
        {
            "Time": f"{step.at_seconds:5.2f}s",
            "Action": _describe_action(step.action),
        }
        for step in plan.steps
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def render_history_panel() -> None:
    history = st.session_state.history
    if not history:
        st.caption("(no commands yet)")
        return

    for entry in history[:20]:
        col_time, col_text, col_summary, col_status = st.columns([2, 5, 4, 1])
        col_time.text(entry["time"])
        col_text.text(f'"{entry["text"]}"')
        col_summary.text(entry["summary"])
        col_status.text(entry["status"])


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="DeckPilot", page_icon="🎚️", layout="centered")
    init_state()

    st.title("🎚️ DeckPilot")
    st.caption("Natural-language control for Mixxx · MIDI via IAC Driver")

    # --- Input form ---
    with st.form("command_form", clear_on_submit=False):
        text = st.text_input(
            "Command",
            placeholder="Type a command, e.g. 'bass swap into deck 2'",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Execute", type="primary", width="stretch")

    if submitted:
        handle_command(text)

    # --- Preset buttons ---
    st.markdown("**Try these:**")
    cols = st.columns(2)
    for i, preset in enumerate(PRESETS):
        with cols[i % 2]:
            if st.button(preset, key=f"preset_{i}", width="stretch"):
                handle_command(preset)

    st.divider()

    # --- Parsed plan panel ---
    st.subheader("📋 Parsed plan")
    render_plan_panel()

    st.divider()

    # --- History panel ---
    st.subheader("📜 History")
    render_history_panel()


if __name__ == "__main__":
    main()
