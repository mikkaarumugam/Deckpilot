"""
DeckPilot dashboard — Streamlit frontend for the DJ control system.

UX patterns at play:
  - Plan-visible-before-audio: st.status renders the parsed plan table
    BEFORE the executor fires the MIDI. Eyes confirm before ears.
  - One-click undo per history entry, with computed inverses.
  - Queue: pre-build a sequence of commands, review/reorder, then commit.
    Same surface that an agent would use to expose its plan.
  - Reset state: hard "go back to neutral" button — pause decks, crossfader
    center, EQs and volumes to default. Useful when something gets weird.

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
from deckpilot.core.undo import inverse_plan, reset_plan


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
    st.session_state.setdefault("queue", [])  # list[str] of pending commands


# ---------------------------------------------------------------------------
# Parsing + execution
# ---------------------------------------------------------------------------

def parse_with_metadata(text: str) -> tuple[ActionPlan, str, float]:
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
    """Parse text, render the plan, execute, log to history."""
    text = text.strip()
    if not text:
        return

    with st.status("Parsing...", expanded=True) as status:
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

        source_label = "⚡ regex" if source == "regex" else "🤖 LLM"
        st.markdown(
            f"**Input:** `{text}`  ·  **Source:** {source_label}  ·  "
            f"**Parse:** `{parse_latency:.2f}s`"
        )
        _render_plan_table(plan)
        status.update(
            label=f"Plan ready ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}). Executing..."
        )

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


def execute_plan_with_status(plan: ActionPlan, label: str, log_text: str) -> None:
    """Execute a pre-computed plan (undo, reset, etc.) with its own status panel."""
    with st.status(label, expanded=True) as status:
        st.markdown(f"**Plan** · {len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}")
        _render_plan_table(plan)
        status.update(label=f"Executing: {label}...")
        executor = get_executor()
        exec_start = time.monotonic()
        executor.run_plan(plan)
        exec_latency = time.monotonic() - exec_start
        status.update(label=f"Done · {exec_latency:.2f}s", state="complete")

    st.session_state.history.insert(0, {
        "time": time.strftime("%H:%M:%S"),
        "text": log_text,
        "summary": f"{len(plan.steps)} steps",
        "status": "✓",
        "detail": f"system, {exec_latency:.2f}s exec",
        "plan": None,  # system-generated plans aren't user-undoable
    })


def execute_queue() -> None:
    """Run every queued command in order."""
    queue: list[str] = st.session_state.queue
    if not queue:
        return
    st.session_state.queue = []   # consume up-front so a failure doesn't loop
    for text in queue:
        execute_command(text)


# ---------------------------------------------------------------------------
# History interactions
# ---------------------------------------------------------------------------

def _trigger_undo(entry_index: int) -> None:
    entry = st.session_state.history[entry_index]
    plan = entry.get("plan")
    if plan is None:
        st.toast("Nothing to undo for this entry.", icon="⚠️")
        return
    inv = inverse_plan(plan)
    if inv is None:
        st.toast("This command can't be cleanly undone.", icon="⚠️")
        return
    st.session_state.pending_system_plan = (inv, f"↶ undo: {entry['text']}", "Undoing...")
    st.rerun()


def _trigger_reset() -> None:
    st.session_state.pending_system_plan = (
        reset_plan(), "🎚️ reset Mixxx state", "Resetting Mixxx state..."
    )
    st.rerun()


def _trigger_clear_history() -> None:
    st.session_state.history = []
    st.toast("History cleared.", icon="🧹")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_queue() -> None:
    queue: list[str] = st.session_state.queue
    header_col, run_col, clear_col = st.columns([5, 2, 2])
    header_col.markdown(f"**📥 Queue ({len(queue)})**")
    if queue:
        if run_col.button("Run queue", type="primary", width="stretch", key="run_queue"):
            execute_queue()
        if clear_col.button("Clear", width="stretch", key="clear_queue"):
            st.session_state.queue = []
            st.toast("Queue cleared.", icon="🧹")
    else:
        st.caption("(empty — submit with the Queue button to add)")
        return

    for i, text in enumerate(queue):
        idx_col, text_col, remove_col = st.columns([1, 8, 1])
        idx_col.text(f"{i + 1}.")
        text_col.text(f'"{text}"')
        if remove_col.button("✕", key=f"queue_remove_{i}", help="Remove from queue"):
            st.session_state.queue.pop(i)
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
    queue_text: str | None = None

    # --- Input form (Execute + Queue) ---
    with st.form("command_form", clear_on_submit=True):
        text = st.text_input(
            "Command",
            placeholder="Type a command, e.g. 'bass swap into deck 2'",
            label_visibility="collapsed",
        )
        exec_col, queue_col = st.columns(2)
        if exec_col.form_submit_button("Execute", type="primary", width="stretch"):
            submit_text = text.strip() or None
        if queue_col.form_submit_button("Queue", width="stretch"):
            queue_text = text.strip() or None

    # --- Presets (always execute, never queue — they're for the demo) ---
    st.markdown("**Try these:**")
    cols = st.columns(2)
    for i, preset in enumerate(PRESETS):
        with cols[i % 2]:
            if st.button(preset, key=f"preset_{i}", width="stretch"):
                submit_text = preset

    st.divider()

    # --- Queue panel ---
    render_queue()
    if queue_text:
        st.session_state.queue.append(queue_text)
        st.rerun()

    st.divider()

    # --- Execution area: fresh command OR a deferred system plan (undo/reset) ---
    pending_system = st.session_state.pop("pending_system_plan", None)
    if submit_text:
        execute_command(submit_text)
    elif pending_system is not None:
        plan, log_text, status_label = pending_system
        execute_plan_with_status(plan, status_label, log_text)

    st.divider()

    # --- History panel with utility buttons ---
    title_col, clear_col, reset_col = st.columns([6, 2, 2])
    title_col.subheader("📜 History  ·  click ↶ to undo")
    if clear_col.button("🧹 Clear history", width="stretch", key="clear_history"):
        _trigger_clear_history()
    if reset_col.button("🎚️ Reset Mixxx", width="stretch", help="Pause both decks, center crossfader, EQs and volumes to neutral", key="reset_state"):
        _trigger_reset()

    render_history()


if __name__ == "__main__":
    main()
