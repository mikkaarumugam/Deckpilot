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
    from deckpilot.adapters.midi_feedback import MixxxFeedback
    from deckpilot.library import LibraryReader


_library: "LibraryReader | None" = None
_library_init_attempted = False

_adapter: MidiAdapter | None = None
_adapter_init_attempted = False

_executor: Executor | None = None

_feedback: "MixxxFeedback | None" = None
_feedback_init_attempted = False


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


def get_adapter() -> MidiAdapter | None:
    """MidiAdapter holds the IAC output port. Returns None if IAC is
    unavailable (Mixxx not running, IAC Driver not enabled)."""
    global _adapter, _adapter_init_attempted
    if _adapter is not None or _adapter_init_attempted:
        return _adapter
    _adapter_init_attempted = True
    try:
        _adapter = MidiAdapter(library=get_library())
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


def stop_feedback() -> None:
    """Tear down MixxxFeedback cleanly. MUST be called on app shutdown
    so rtmidi's callback thread doesn't reference torn-down state.
    See the segfault gotcha in docs/GOTCHAS.md."""
    global _feedback
    if _feedback is not None:
        _feedback.stop()
        _feedback = None
