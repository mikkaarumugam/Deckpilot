"""
DeckPilot dashboard — Streamlit frontend.

Sidebar layout:
  - Left sidebar: app name, preset buttons, queue panel, utility controls.
  - Main area: input form, parsed-plan + execution status, history.

UX patterns at play:
  - Plan-visible-before-audio: st.status renders the parsed plan table
    BEFORE the executor fires the MIDI. Eyes confirm before ears.
  - One-click ↶ undo per history entry, with computed inverses.
  - Queue: pre-build a sequence of commands, review/reorder in the
    sidebar, then commit. Same surface an agent would use to expose
    its plan to the user.
  - Reset Mixxx: hard "go back to neutral" panic button.

Sidebar button clicks (Run queue, Reset, etc.) defer execution to the
main area via session_state so the status panels and any new history
entries render in the right column.

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
# Visual polish: custom CSS injection (Inter + JetBrains Mono, button polish,
# colored source pills, status icons). The base theme lives in
# .streamlit/config.toml — this layer adds typography and component detail
# that the toml schema can't reach.
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
<style>
/* --- Google Fonts --- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

html, body, [class*="st-"], button, input, textarea, p, span, div {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}

/* --- Code / inline `` blocks: use JetBrains Mono and a subtle dark chip --- */
code, kbd, samp, [data-testid="stDataFrame"] {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace !important;
}
code {
    background: #1f1f28 !important;
    color: #c7c7d1 !important;
    padding: 2px 7px !important;
    border-radius: 4px !important;
    font-size: 0.86em !important;
    border: 1px solid #2a2a35;
}

/* --- Headings: tight letter-spacing, semi-bold weight --- */
h1, h2, h3, h4 {
    font-weight: 600 !important;
    letter-spacing: -0.015em !important;
    color: #f4f4f5 !important;
}
h3 { font-size: 1.15rem !important; }

/* --- Caption text muted --- */
[data-testid="stCaptionContainer"], .stCaption {
    color: #8b8b96 !important;
}

/* --- Buttons: rounded, smooth hover --- */
.stButton > button, .stFormSubmitButton > button {
    border-radius: 6px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
    border: 1px solid #2a2a35 !important;
    background: #1a1a22 !important;
    color: #e4e4e7 !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
    background: #22222c !important;
    border-color: #6366f1 !important;
    color: #f4f4f5 !important;
}
/* Primary button — accent fill */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {
    background: #6366f1 !important;
    border-color: #6366f1 !important;
    color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {
    background: #5558e3 !important;
    border-color: #5558e3 !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.25);
}

/* --- Sidebar background, slightly different elevation --- */
section[data-testid="stSidebar"] {
    background: #14141a !important;
    border-right: 1px solid #1f1f28 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: #1a1a22 !important;
}

/* --- Status / expander panel (where parsed plan renders) --- */
div[data-testid="stExpander"] details {
    background: #16161d !important;
    border: 1px solid #2a2a35 !important;
    border-radius: 8px !important;
}
div[data-testid="stExpander"] summary {
    font-weight: 500 !important;
}

/* --- Dataframe (plan table): tighter, mono, less Streamlit chrome --- */
[data-testid="stDataFrame"] {
    border-radius: 6px !important;
    border: 1px solid #2a2a35 !important;
}

/* --- Input box: better contrast --- */
[data-testid="stTextInput"] input {
    background: #16161d !important;
    border: 1px solid #2a2a35 !important;
    color: #e4e4e7 !important;
    font-size: 0.95rem !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 1px #6366f1 !important;
}

/* --- Dividers: subtle --- */
hr {
    border-color: #1f1f28 !important;
    margin: 1.2rem 0 !important;
    opacity: 0.7;
}

/* --- Source pills (regex / LLM badges) --- */
.source-pill {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 11px;
    font-size: 0.78em;
    font-weight: 500;
    letter-spacing: 0.01em;
    margin-left: 4px;
}
.source-pill.regex {
    background: rgba(16, 185, 129, 0.12);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.25);
}
.source-pill.llm {
    background: rgba(99, 102, 241, 0.14);
    color: #a5a8ff;
    border: 1px solid rgba(99, 102, 241, 0.3);
}

/* --- History status indicators --- */
.status-ok { color: #34d399 !important; font-weight: 600; }
.status-fail { color: #f87171 !important; font-weight: 600; }

/* --- Sidebar footer (version tag) --- */
.sidebar-footer {
    color: #4a4a55;
    font-size: 0.75em;
    margin-top: 1.5rem;
    text-align: center;
    font-family: 'JetBrains Mono', monospace !important;
}
</style>
"""


def _inject_css() -> None:
    """Inject the custom CSS layer. Called once per rerun, at the top of main()."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Adapter + state setup
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
    st.session_state.setdefault("queue", [])


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
        {"Time": f"{step.at_seconds:5.2f}s", "Action": _describe_action(step.action)}
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
            status.update(label=f"Could not parse: {exc}", state="error", expanded=True)
            st.session_state.history.insert(0, {
                "time": time.strftime("%H:%M:%S"),
                "text": text,
                "summary": "declined",
                "status": "✗",
                "detail": str(exc),
                "plan": None,
            })
            return

        source_pill = (
            '<span class="source-pill regex">⚡ regex</span>'
            if source == "regex"
            else '<span class="source-pill llm">🤖 LLM</span>'
        )
        st.markdown(
            f"**Input:** `{text}`  &nbsp;·&nbsp;  **Source:** {source_pill}  &nbsp;·&nbsp;  "
            f"**Parse:** `{parse_latency:.2f}s`",
            unsafe_allow_html=True,
        )
        _render_plan_table(plan)
        status.update(
            label=f"Plan ready ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}). Executing..."
        )

        executor = get_executor()
        exec_start = time.monotonic()
        executor.run_plan(plan)
        exec_latency = time.monotonic() - exec_start

        status.update(label=f"Done · {exec_latency:.2f}s execution", state="complete", expanded=True)

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
        status.update(label=f"Done · {exec_latency:.2f}s", state="complete", expanded=True)

    st.session_state.history.insert(0, {
        "time": time.strftime("%H:%M:%S"),
        "text": log_text,
        "summary": f"{len(plan.steps)} steps",
        "status": "✓",
        "detail": f"system, {exec_latency:.2f}s exec",
        "plan": None,
    })


# ---------------------------------------------------------------------------
# History / undo / reset triggers
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
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> str | None:
    """Build sidebar widgets. Return a preset's text if one was clicked."""
    preset_clicked: str | None = None

    with st.sidebar:
        st.title("🎚️ DeckPilot")
        st.caption("Natural-language Mixxx control")

        st.divider()

        # --- Presets ---
        st.markdown("**Try these**")
        for i, preset in enumerate(PRESETS):
            if st.button(preset, key=f"preset_{i}", width="stretch"):
                preset_clicked = preset

        st.divider()

        # --- Queue ---
        queue: list[str] = st.session_state.queue
        st.markdown(f"**📥 Queue** · {len(queue)} pending")
        if not queue:
            st.caption("Use the *Queue* button under the input to add commands.")
        else:
            for i, text in enumerate(queue):
                cols = st.columns([7, 1])
                cols[0].text(f"{i + 1}. {text}")
                if cols[1].button("✕", key=f"queue_remove_{i}", help="Remove"):
                    st.session_state.queue.pop(i)
                    st.rerun()
            col_run, col_clear = st.columns(2)
            if col_run.button("Run queue", type="primary", key="run_queue", width="stretch"):
                # Defer execution to the main area so status panels render there.
                st.session_state.queue_to_run = list(st.session_state.queue)
                st.session_state.queue = []
                st.rerun()
            if col_clear.button("Clear", key="clear_queue", width="stretch"):
                st.session_state.queue = []
                st.rerun()

        st.divider()

        # --- Controls ---
        st.markdown("**Controls**")
        if st.button("🧹 Clear history", key="clear_history", width="stretch"):
            _trigger_clear_history()
        if st.button("🎚️ Reset Mixxx", key="reset_state", width="stretch",
                     help="Pause both decks, center crossfader, EQs/volumes to neutral"):
            _trigger_reset()

        # --- Sidebar footer ---
        st.markdown(
            '<div class="sidebar-footer">DeckPilot · v0.1.0</div>',
            unsafe_allow_html=True,
        )

    return preset_clicked


# ---------------------------------------------------------------------------
# History panel (main area)
# ---------------------------------------------------------------------------

def render_history() -> None:
    history = st.session_state.history
    if not history:
        st.caption("(no commands yet)")
        return

    for i, entry in enumerate(history[:20]):
        col_time, col_text, col_summary, col_status, col_undo = st.columns([2, 5, 4, 1, 1])
        col_time.markdown(f"<code>{entry['time']}</code>", unsafe_allow_html=True)
        col_text.markdown(f'"{entry["text"]}"')
        col_summary.markdown(f"<code>{entry['summary']}</code>", unsafe_allow_html=True)
        status_class = "status-ok" if entry["status"] == "✓" else "status-fail"
        col_status.markdown(
            f'<span class="{status_class}">{entry["status"]}</span>',
            unsafe_allow_html=True,
        )
        if entry.get("plan") is not None:
            if col_undo.button("↶", key=f"undo_{i}", help="Undo this command"):
                _trigger_undo(i)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="DeckPilot",
        page_icon="🎚️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()
    init_state()

    # Sidebar renders first so we can capture preset clicks before the main area runs.
    sidebar_preset = render_sidebar()

    submit_text: str | None = sidebar_preset
    queue_text: str | None = None

    # --- Main area: input form ---
    with st.form("command_form", clear_on_submit=True):
        text = st.text_input(
            "Command",
            placeholder="Type a DJ command — e.g. 'bass swap into deck 2 over 4 seconds'",
            label_visibility="collapsed",
        )
        exec_col, queue_col = st.columns(2)
        if exec_col.form_submit_button("Execute", type="primary", width="stretch"):
            submit_text = text.strip() or None
        if queue_col.form_submit_button("Queue", width="stretch"):
            queue_text = text.strip() or None

    # Queue additions: append, then rerun so the sidebar updates.
    if queue_text:
        st.session_state.queue.append(queue_text)
        st.toast(f"Queued: {queue_text!r}", icon="📥")
        st.rerun()

    # --- Execution area (always renders here, never in sidebar) ---
    queue_to_run = st.session_state.pop("queue_to_run", None)
    pending_system = st.session_state.pop("pending_system_plan", None)

    if queue_to_run:
        for text in queue_to_run:
            execute_command(text)
    elif submit_text:
        execute_command(submit_text)
    elif pending_system is not None:
        plan, log_text, status_label = pending_system
        execute_plan_with_status(plan, status_label, log_text)

    # --- History panel ---
    st.divider()
    st.subheader("📜 History  ·  click ↶ to undo")
    render_history()


if __name__ == "__main__":
    main()
