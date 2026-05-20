"""
DeckPilot dashboard — Streamlit frontend for the DJ control system.

What this gives you that the CLI doesn't:
  - A focused text input you can type or dictate into.
  - The parsed plan renders BEFORE audio fires — the AI's structured
    output is visible while execution happens, so you build trust in
    the system without needing an explicit "confirm" click.
  - One-click ↶ undo on every history entry. The cost of an AI miss is
    bounded by recovery time, not action permanence.
  - A running history of every command, what source parsed it
    (regex vs LLM), and how long parsing + execution took.

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
from deckpilot.core.undo import inverse_plan


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
    """Cached so the IAC port isn't reopened on every Streamlit rerun."""
    if "executor" not in st.session_state:
        adapter = MidiAdapter()
        st.session_state.executor = Executor(adapter)
        st.session_state.port_name = adapter.port_name
    return st.session_state.executor


def init_state() -> None:
    st.session_state.setdefault("history", [])


# ---------------------------------------------------------------------------
# Parsing + execution
# ---------------------------------------------------------------------------

def parse_with_metadata(text: str) -> tuple[ActionPlan, str, float]:
    """Parse and return (plan, source, parse_seconds)."""
    start = time.monotonic()
    plan = regex_parser.parse(text)
    if plan is not None:
        return plan, "regex", time.monotonic() - start
    plan = facade_parse(text)
    return plan, "llm", time.monotonic() - start


def _describe_action(action: Any) -> str:
    cls = type(action).__name__
    fields = ", ".join(f"{k}={v}" for k, v in asdict(action).items())
    return f"{cls}({fields})"


def _render_plan_table(plan: ActionPlan) -> None:
    rows = [
        {
            "Time": f"{step.at_seconds:5.2f}s",
            "Action": _describe_action(step.action),
        }
        for step in plan.steps
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def execute_command(text: str) -> None:
    """Parse text, render the plan, execute, and log to history."""
    text = text.strip()
    if not text:
        return

    with st.status("Parsing...", expanded=True) as status:
        # --- Parse ---
        try:
            plan, source, parse_latency = parse_with_metadata(text)
        except ParseError as exc:
            status.update(label=f"Could not parse: {exc}", state="error")
            st.session_state.history.insert(0, {
                "time": time.strftime("%H:%M:%S"),
                "text": text,
                "summary": "declined",
                "status": "✗",
                "detail": str(exc),
                "plan": None,
            })
            return

        # --- Show parsed plan immediately ---
        source_label = "⚡ regex" if source == "regex" else "🤖 LLM"
        st.markdown(
            f"**Input:** `{text}`  ·  **Source:** {source_label}  ·  "
            f"**Parse:** `{parse_latency:.2f}s`"
        )
        _render_plan_table(plan)
        status.update(
            label=f"Plan ready ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}). Executing..."
        )

        # --- Execute ---
        executor = get_executor()
        exec_start = time.monotonic()
        executor.run_plan(plan)
        exec_latency = time.monotonic() - exec_start

        status.update(label=f"Done · {exec_latency:.2f}s execution", state="complete")

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
        "detail": f"{source}, {parse_latency:.2f}s parse + {exec_latency:.2f}s exec",
        "plan": plan,
    })


def execute_undo(undo_plan: ActionPlan, original_text: str) -> None:
    """Execute a pre-computed undo plan, with its own status panel."""
    with st.status(f"Undoing: {original_text!r}", expanded=True) as status:
        st.markdown(f"**Undo plan** · {len(undo_plan.steps)} step{'s' if len(undo_plan.steps) != 1 else ''}")
        _render_plan_table(undo_plan)
        status.update(label="Executing undo...")

        executor = get_executor()
        exec_start = time.monotonic()
        executor.run_plan(undo_plan)
        exec_latency = time.monotonic() - exec_start

        status.update(label=f"Undo done · {exec_latency:.2f}s", state="complete")

    st.session_state.history.insert(0, {
        "time": time.strftime("%H:%M:%S"),
        "text": f"↶ undo: {original_text}",
        "summary": f"{len(undo_plan.steps)} steps",
        "status": "✓",
        "detail": f"undo, {exec_latency:.2f}s exec",
        "plan": None,   # don't allow undo-of-undo
    })


def _trigger_undo(entry_index: int) -> None:
    """Compute the inverse plan and stash it for the next rerun to execute."""
    entry = st.session_state.history[entry_index]
    plan = entry.get("plan")
    if plan is None:
        st.toast("Nothing to undo for this entry.", icon="⚠️")
        return
    inv = inverse_plan(plan)
    if inv is None:
        st.toast("This command can't be cleanly undone.", icon="⚠️")
        return
    # Defer to next rerun so the status panel renders in the consistent spot
    # below the input area, not jammed into the history row.
    st.session_state.pending_undo = (inv, entry["text"])
    st.rerun()


def render_history() -> None:
    history = st.session_state.history
    if not history:
        st.caption("(no commands yet)")
        return

    for i, entry in enumerate(history[:20]):
        col_time, col_text, col_summary, col_status, col_undo = st.columns([2, 5, 4, 1, 1])
        col_time.text(entry["time"])
        col_text.text(f'"{entry["text"]}"')
        col_summary.text(entry["summary"])
        col_status.text(entry["status"])
        if entry.get("plan") is not None:
            if col_undo.button("↶", key=f"undo_{i}", help="Undo this command"):
                _trigger_undo(i)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="DeckPilot", page_icon="🎚️", layout="centered")
    init_state()

    st.title("🎚️ DeckPilot")
    st.caption("Natural-language control for Mixxx · MIDI via IAC Driver")

    submit_text: str | None = None

    # --- Input form ---
    with st.form("command_form", clear_on_submit=False):
        text = st.text_input(
            "Command",
            placeholder="Type a command, e.g. 'bass swap into deck 2'",
            label_visibility="collapsed",
        )
        if st.form_submit_button("Execute", type="primary", width="stretch"):
            submit_text = text.strip() or None

    # --- Preset buttons ---
    st.markdown("**Try these:**")
    cols = st.columns(2)
    for i, preset in enumerate(PRESETS):
        with cols[i % 2]:
            if st.button(preset, key=f"preset_{i}", width="stretch"):
                submit_text = preset

    st.divider()

    # --- Command execution area (consistent location for both fresh commands and undos) ---
    pending_undo = st.session_state.pop("pending_undo", None)
    if submit_text:
        execute_command(submit_text)
    elif pending_undo is not None:
        undo_plan, original_text = pending_undo
        execute_undo(undo_plan, original_text)

    st.divider()
    st.subheader("📜 History  ·  click ↶ to undo")
    render_history()


if __name__ == "__main__":
    main()
