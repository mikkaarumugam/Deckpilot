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

from deckpilot.adapters.midi import LoadTrackSuggestion, MidiAdapter
from deckpilot.adapters.midi_feedback import MixxxFeedback
from deckpilot.core.actions import ActionPlan, LoadTrack
from deckpilot.core.executor import Executor
from deckpilot.core.parser import parse as facade_parse
from deckpilot.core.parser import regex as regex_parser
from deckpilot.core.parser.errors import ParseError
from deckpilot.core.undo import inverse_plan, reset_plan
from deckpilot.library import LibraryReader, Track


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
/* Material Symbols — Streamlit's icon font. Explicitly imported so it
   doesn't rely on Streamlit's bundled copy being served correctly, and so
   our restore rule below has a guaranteed font to fall back on. */
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded&family=Material+Symbols+Outlined&display=swap');

/* Inter as default text font via body (inherits everywhere) and a few
   explicit Streamlit text containers. No !important so the icon rule
   below can win on icon spans. */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stSidebar"],
[data-testid="stMarkdown"],
[data-testid="stMarkdown"] p,
[data-testid="stMarkdown"] li,
[data-testid="stMarkdown"] td,
[data-testid="stTextInput"] input,
[data-testid="stCaptionContainer"] {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

/* RESTORE the Material Symbols font for Streamlit's icon spans.
   The stable selector is `data-testid="stIconMaterial"` — Streamlit puts
   it on every Material-icon span (sidebar collapse, status chevrons,
   toast icons, etc.). Without this rule, our body Inter cascades down
   and the icon NAMES render as plain text ("keyboard_double_arrow_left",
   "arrow_drop_down"). The Emotion class hashes (st-emotion-cache-...)
   change between Streamlit builds, so we target the test-id only. */
[data-testid="stIconMaterial"],
.material-icons,
.material-symbols-rounded,
.material-symbols-outlined {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined",
                 "Material Icons" !important;
    font-feature-settings: "liga" !important;
    /* ligatures = the mechanism that turns the icon NAME into the glyph */
    -webkit-font-smoothing: antialiased !important;
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
    """Cached so the IAC port isn't reopened on every Streamlit rerun.

    Inject the LibraryReader into the MidiAdapter so LoadTrack actions
    can resolve file paths from track ids. Adapter still works if the
    library isn't available — LoadTrack just raises a helpful error.
    """
    if "executor" not in st.session_state:
        adapter = MidiAdapter(library=get_library())
        st.session_state.executor = Executor(adapter)
        st.session_state.port_name = adapter.port_name
    return st.session_state.executor


def get_feedback() -> MixxxFeedback | None:
    """Singleton MixxxFeedback. Returns None (and remembers the failure)
    if the IAC input port isn't available — keeps the dashboard usable
    even when Mixxx isn't running."""
    if "feedback" in st.session_state:
        return st.session_state.feedback
    if st.session_state.get("feedback_failed"):
        return None
    try:
        st.session_state.feedback = MixxxFeedback().start()
    except Exception as exc:
        st.session_state.feedback_failed = str(exc)
        return None
    return st.session_state.feedback


def get_library() -> LibraryReader | None:
    """Singleton LibraryReader. None if the Mixxx DB isn't found."""
    if "library" in st.session_state:
        return st.session_state.library
    if st.session_state.get("library_failed"):
        return None
    try:
        st.session_state.library = LibraryReader()
    except Exception as exc:
        st.session_state.library_failed = str(exc)
        return None
    return st.session_state.library


# BPM tolerance for library lookup. The 7-bit CC encoding of BPM
# introduces ~0.5 BPM round-trip error (140 BPM range / 127 steps =
# 1.1 BPM per step, ±0.55 BPM each side). 0.6 stays inside one step so
# adjacent CC values don't both match the same library track.
_BPM_MATCH_TOLERANCE = 0.6


def _match_track(library: LibraryReader, bpm: float) -> Track | None:
    """Find the unique library track at this BPM. Returns None if zero
    or multiple matches — honest about ambiguity instead of guessing."""
    if bpm <= 0:
        return None
    candidates = library.find_by_bpm(bpm - _BPM_MATCH_TOLERANCE,
                                     bpm + _BPM_MATCH_TOLERANCE)
    return candidates[0] if len(candidates) == 1 else None


def init_state() -> None:
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("queue", [])


# ---------------------------------------------------------------------------
# Parsing + execution
# ---------------------------------------------------------------------------

def parse_with_metadata(text: str) -> tuple[ActionPlan, str, float]:
    """Parse with runtime context: library + live deck state from Mixxx
    feedback. Regex doesn't use them; the LLM does (track selection,
    'pick the deck that isn't playing', BPM-compatible matching)."""
    start = time.monotonic()
    plan = regex_parser.parse(text)
    if plan is not None:
        return plan, "regex", time.monotonic() - start

    library = get_library()
    feedback = get_feedback()
    deck_state = feedback.snapshot() if feedback is not None else None
    plan = facade_parse(text, library=library, deck_state=deck_state)
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
        try:
            executor.run_plan(plan)
            exec_latency = time.monotonic() - exec_start
            status.update(
                label=f"Done · {exec_latency:.2f}s execution",
                state="complete", expanded=True,
            )
        except LoadTrackSuggestion as sug:
            # Not an error — the executor hit a LoadTrack step. Mixxx 2.5
            # has no path-based load API, so we surface the LLM's choice
            # to the user as a suggestion card and stop the rest of the
            # plan (subsequent steps assume the load happened).
            exec_latency = time.monotonic() - exec_start
            _render_suggestion_card(sug)
            status.update(
                label="Suggestion ready — load manually in Mixxx",
                state="complete", expanded=True,
            )
            st.session_state.history.insert(0, {
                "time": time.strftime("%H:%M:%S"),
                "text": text,
                "summary": _describe_suggestion(sug),
                "status": "💡",
                "detail": f"{source}, {parse_latency:.2f}s parse — track suggestion",
                "plan": None,
            })
            return

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


def _describe_suggestion(sug: LoadTrackSuggestion) -> str:
    if sug.track is None:
        return f"Suggest track_id={sug.action.track_id} on deck {sug.action.deck}"
    return f"Suggest: {sug.track.title[:50]} on deck {sug.action.deck}"


def _render_suggestion_card(sug: LoadTrackSuggestion) -> None:
    """Surface the LLM's track choice as a styled card. Mixxx 2.5's
    controller API has no path-based load, so this is the deliverable:
    library-aware reasoning made visible. The user loads manually if
    they want to follow the suggestion."""
    t = sug.track
    if t is None:
        st.warning(
            f"LLM suggested track id={sug.action.track_id} on deck "
            f"{sug.action.deck}, but the library reader couldn't resolve it."
        )
        return

    bpm = f"{t.bpm:.1f} BPM" if t.bpm > 0 else "BPM not analysed"
    key = t.key or "—"
    genre = t.genre or "—"

    st.markdown(
        f"""
<div style="background:#16161d;border:1px solid #6366f1;border-radius:8px;
            padding:1rem 1.2rem;margin:0.6rem 0;">
  <div style="color:#a5a8ff;font-size:0.78em;font-weight:600;letter-spacing:0.05em;
              text-transform:uppercase;margin-bottom:0.3rem;">
    💡 AI suggests for deck {sug.action.deck}
  </div>
  <div style="font-weight:600;color:#f4f4f5;font-size:1.05em;margin-bottom:0.2rem;">
    {t.title}
  </div>
  <div style="color:#a1a1aa;font-size:0.88em;margin-bottom:0.6rem;">
    {t.artist}
  </div>
  <div style="display:flex;gap:1rem;font-size:0.82em;color:#8b8b96;">
    <span><code>{bpm}</code></span>
    <span>key: <code>{key}</code></span>
    <span>genre: <code>{genre}</code></span>
  </div>
  <div style="color:#6b6b75;font-size:0.78em;margin-top:0.6rem;
              border-top:1px solid #2a2a35;padding-top:0.5rem;">
    Mixxx 2.5 has no path-based load API — drag this onto deck {sug.action.deck}
    in Mixxx if you want to follow the suggestion.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


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

@st.fragment(run_every="1s")
def _render_deck_state_fragment() -> None:
    """Live deck state, refreshed once per second via st.fragment.

    A fragment re-runs in isolation — the rest of the page stays put.
    That lets us poll MixxxFeedback at 1Hz without rebuilding the form,
    queue, or history every tick.

    Track identity comes from a BPM lookup against the library DB. MIDI
    can't carry the title string (no JS API for track metadata in Mixxx
    controller scripts), so we match the live BPM against
    `library.bpm`. Unambiguous in this library; if multiple tracks
    shared a BPM the lookup would return None instead of guessing.
    """
    fb = get_feedback()
    if fb is None:
        err = st.session_state.get("feedback_failed", "unknown error")
        st.caption(f"⚠️ Feedback unavailable: {err}")
        return

    library = get_library()
    snap = fb.snapshot()
    for n in (1, 2):
        d = snap.deck(n)
        icon = "▶︎" if d.playing else "⏸"
        bpm_text = f"{d.bpm:.1f} BPM" if d.bpm > 0 else "—"

        # Library lookup. Falls back gracefully if the DB isn't reachable.
        track = _match_track(library, d.bpm) if library is not None else None
        if track is not None:
            # YouTube-DL titles already embed the artist; show the title
            # alone to avoid "Artist — Artist - Title" duplication.
            track_label = track.title or f"{track.artist} — (untitled)"
        elif d.bpm > 0:
            # Got a BPM, no library match — could be a track loaded from
            # outside the library, or a library track at an ambiguous BPM.
            track_label = "(not in library)"
        else:
            # file_bpm = 0 means the track hasn't been analysed yet (or
            # no track is loaded). Right-click → Analyze in Mixxx to fix.
            track_label = "(BPM not yet analysed)"

        st.markdown(
            f"<div style='margin-bottom: 0.7rem;'>"
            f"<div style='font-weight:600;color:#e4e4e7'>Deck {n}  "
            f"<span style='color:{'#34d399' if d.playing else '#8b8b96'};font-weight:500'>"
            f"{icon}</span>  "
            f"<code style='font-size:0.78em'>{bpm_text}</code>"
            f"</div>"
            f"<div style='color:#a1a1aa;font-size:0.82em;margin-top:2px;"
            f"max-width:100%;overflow:hidden;text-overflow:ellipsis;"
            f"white-space:nowrap'>{track_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_sidebar() -> str | None:
    """Build sidebar widgets. Return a preset's text if one was clicked."""
    preset_clicked: str | None = None

    with st.sidebar:
        st.title("🎚️ DeckPilot")
        st.caption("Natural-language Mixxx control")

        st.divider()

        # --- Live deck state (Session 2 — Mixxx → Python read-back) ---
        st.markdown("**🎧 Live state**")
        _render_deck_state_fragment()

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
