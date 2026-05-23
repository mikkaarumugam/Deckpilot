"""Process-wide singletons. Lazy-instantiated on first use.

Each getter returns `None` (or raises a contained exception) if the
underlying resource isn't available. Callers should handle the None
case and degrade gracefully — e.g. /state returns empty decks if MIDI
feedback can't open, /parse still works without a LibraryReader (the
LLM just won't get a library context block).

Lifecycle:
- LibraryReader opens fresh SQLite connections per query, no teardown.
- MidiAdapter holds the IAC output port. Process exit closes it.
- MixxxFeedback holds the IAC input port + a callback thread. Explicit
  `stop_feedback()` MUST be called at shutdown so rtmidi cancels its
  callback cleanly (see DECISIONS § D-016 + the segfault gotcha).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deckpilot.adapters.midi import MidiAdapter
from deckpilot.core.executor import Executor

if TYPE_CHECKING:
    from deckpilot.adapters.gui import MixxxGuiAdapter
    from deckpilot.adapters.midi_feedback import MixxxFeedback
    from deckpilot.library import LibraryReader


_library: "LibraryReader | None" = None
_library_init_attempted = False

_adapter: MidiAdapter | None = None
_adapter_init_attempted = False

_gui: "MixxxGuiAdapter | None" = None
_gui_init_attempted = False

_executor: Executor | None = None

_feedback: "MixxxFeedback | None" = None
_feedback_init_attempted = False

# AgentRuntime singleton — at most one schedule active per process.
# Created lazily once both Executor + Feedback are available.
_agent_runtime = None


def get_library() -> "LibraryReader | None":
    """LibraryReader is read-only — safe to keep across requests."""
    global _library, _library_init_attempted
    if _library is not None or _library_init_attempted:
        return _library
    _library_init_attempted = True
    try:
        from deckpilot.library import LibraryReader

        _library = LibraryReader()
    except Exception:
        # Mixxx DB not found, or other init failure — degrade to None.
        _library = None
    return _library


def get_gui_adapter() -> "MixxxGuiAdapter | None":
    """MixxxGuiAdapter drives Mixxx's GUI for the one action MIDI can't
    handle (path-based track load). Lazy — instantiating is cheap (no
    ports / threads), so this is mostly a consistency helper.

    Returns None only if the import fails (e.g. running on non-macOS),
    so we degrade gracefully to the manual-drag suggestion path."""
    global _gui, _gui_init_attempted
    if _gui is not None or _gui_init_attempted:
        return _gui
    _gui_init_attempted = True
    try:
        from deckpilot.adapters.gui import MixxxGuiAdapter

        _gui = MixxxGuiAdapter()
    except Exception:
        _gui = None
    return _gui


def get_adapter() -> MidiAdapter | None:
    """MidiAdapter holds the IAC output port. Returns None if IAC is
    unavailable (Mixxx not running, IAC Driver not enabled).

    Wires in the GUI adapter so LoadTrack actions can fire via Mixxx's
    GUI when the chosen track is uniquely identifiable (D-019)."""
    global _adapter, _adapter_init_attempted
    if _adapter is not None or _adapter_init_attempted:
        return _adapter
    _adapter_init_attempted = True
    try:
        _adapter = MidiAdapter(library=get_library(), gui=get_gui_adapter())
    except Exception:
        _adapter = None
    return _adapter


def get_executor() -> Executor | None:
    """Executor depends on the adapter. Returns None if the adapter
    couldn't initialise."""
    global _executor
    if _executor is not None:
        return _executor
    adapter = get_adapter()
    if adapter is None:
        return None
    _executor = Executor(adapter)
    return _executor


def get_feedback() -> "MixxxFeedback | None":
    """MixxxFeedback opens IAC as input + spawns a callback thread.
    Returns None if it couldn't connect."""
    global _feedback, _feedback_init_attempted
    if _feedback is not None or _feedback_init_attempted:
        return _feedback
    _feedback_init_attempted = True
    try:
        from deckpilot.adapters.midi_feedback import MixxxFeedback

        _feedback = MixxxFeedback().start()
    except Exception:
        _feedback = None
    return _feedback


def get_agent_runtime():
    """AgentRuntime singleton — holds at most one active AgentSchedule
    + a background poll task. Returns None if either the executor or
    feedback couldn't initialise (no MIDI / no Mixxx → no agent loop)."""
    global _agent_runtime
    if _agent_runtime is not None:
        return _agent_runtime
    executor = get_executor()
    if executor is None:
        return None

    # Lazy import to avoid a circular dependency on bootup
    # (agent_runtime imports MixxxState which lives in deckpilot, fine,
    # but we still want this to be cheap when no one calls /agent/*).
    from .agent_runtime import AgentRuntime

    def _snap():
        fb = get_feedback()
        return fb.snapshot() if fb is not None else None

    _agent_runtime = AgentRuntime(executor=executor, feedback_snapshot=_snap)
    return _agent_runtime


def stop_feedback() -> None:
    """Tear down MixxxFeedback cleanly. MUST be called on app shutdown
    so rtmidi's callback thread doesn't reference torn-down state.
    See the segfault gotcha in docs/GOTCHAS.md."""
    global _feedback
    if _feedback is not None:
        _feedback.stop()
        _feedback = None
