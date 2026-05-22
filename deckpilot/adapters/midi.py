"""
MidiAdapter — turns atomic DJActions into MIDI messages and ships them
through a virtual MIDI port (the macOS IAC Driver). Mixxx interprets the
incoming MIDI via the mapping in adapters/mappings/mixxx.midi.xml.

Composite/time-based actions (FadeToDeck) are handled by the Executor,
which expands them into a stream of atomic SetCrossfader calls dispatched
through this adapter.

The note/CC numbers live in module-level constants below. They MUST match
the numbers in the Mixxx mapping XML. If you change one, change the other.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import rtmidi

from deckpilot.adapters.base import Adapter
from deckpilot.core.actions import (
    DJAction,
    HotCue,
    LoadTrack,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetVolume,
    Sync,
)

if TYPE_CHECKING:
    from deckpilot.library import LibraryReader, Track


class LoadTrackSuggestion(Exception):
    """Raised when the executor encounters a LoadTrack action.

    Not a real error — a flow-control signal. The dashboard catches
    this, renders the suggestion to the user, and stops executing the
    rest of the plan (subsequent steps would target an unloaded deck).
    """

    def __init__(self, action: "LoadTrack", track: "Track | None") -> None:
        self.action = action
        self.track = track
        if track is not None:
            super().__init__(
                f"Suggested track for deck {action.deck}: "
                f"{track.artist} — {track.title} ({track.bpm:.1f} BPM)"
            )
        else:
            super().__init__(
                f"Suggested track id={action.track_id} for deck "
                f"{action.deck} (not resolvable: no library reader)"
            )


# --- MIDI status bytes (all on channel 1; lower nibble is the channel - 1) ---
NOTE_ON = 0x90
NOTE_OFF = 0x80
CONTROL_CHANGE = 0xB0


# --- Note / CC numbers — keep in sync with mixxx.midi.xml ---

# Play/pause (script bindings in Mixxx — separate notes for each intent).
PLAY_NOTES = {1: 0x3C, 2: 0x3E}     # 60, 62
PAUSE_NOTES = {1: 0x3D, 2: 0x3F}    # 61, 63

# Crossfader (CC 20).
CROSSFADER_CC = 0x14

# Loop toggles (8 beats only in v0.1).
LOOP_NOTES = {1: 0x46, 2: 0x47}     # 70, 71

# Nudge (rate_temp_up/down — held while button is down).
NUDGE_NOTES = {
    (1, "forward"): 0x50,           # 80
    (1, "back"): 0x51,              # 81
    (2, "forward"): 0x52,           # 82
    (2, "back"): 0x53,              # 83
}
NUDGE_HOLD_SECONDS = 0.1

# Beatsync (one-shot trigger).
SYNC_NOTES = {1: 0x5A, 2: 0x5B}     # 90, 91

# Hot cues — 8 cues × 2 decks. Notes 100..107 (deck 1), 108..115 (deck 2).
def _hotcue_note(deck: int, cue: int) -> int:
    base = 0x64 if deck == 1 else 0x6C  # 100 or 108
    return base + (cue - 1)

# EQ bands per deck (CC 30..35).
EQ_CC = {
    (1, "low"):  0x1E,              # 30
    (1, "mid"):  0x1F,              # 31
    (1, "high"): 0x20,              # 32
    (2, "low"):  0x21,              # 33
    (2, "mid"):  0x22,              # 34
    (2, "high"): 0x23,              # 35
}

# Channel volume (CC 40, 41).
VOLUME_CC = {1: 0x28, 2: 0x29}

DEFAULT_PORT_NAME = "IAC Driver Bus 1"


class MidiAdapter(Adapter):
    """Dispatches atomic DJActions as MIDI messages.

    `library` is optional: only needed to dispatch LoadTrack actions
    (we look up the file path from the library DB). The adapter still
    works without it — LoadTrack just raises a helpful error.
    """

    def __init__(
        self,
        port_name: str = DEFAULT_PORT_NAME,
        library: "LibraryReader | None" = None,
    ) -> None:
        self._midi_out = rtmidi.MidiOut()
        ports = self._midi_out.get_ports()
        try:
            port_index = next(i for i, name in enumerate(ports) if port_name in name)
        except StopIteration as exc:
            raise RuntimeError(
                f"MIDI port matching {port_name!r} not found. "
                f"Available ports: {ports!r}. "
                "Is the IAC Driver enabled in Audio MIDI Setup?"
            ) from exc
        self._midi_out.open_port(port_index)
        self._port_name = ports[port_index]
        self._library = library

    @property
    def port_name(self) -> str:
        return self._port_name

    def dispatch(self, action: DJAction) -> None:
        """Execute one atomic action by sending the corresponding MIDI message(s)."""
        if isinstance(action, PlayDeck):
            self._note_on(PLAY_NOTES[action.deck], velocity=127)

        elif isinstance(action, PauseDeck):
            self._note_on(PAUSE_NOTES[action.deck], velocity=127)

        elif isinstance(action, SetCrossfader):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(CROSSFADER_CC, round(clamped * 127))

        elif isinstance(action, LoopDeck):
            self._note_on(LOOP_NOTES[action.deck], velocity=127)

        elif isinstance(action, NudgeDeck):
            note = NUDGE_NOTES[(action.deck, action.direction)]
            self._note_on(note, velocity=127)
            time.sleep(NUDGE_HOLD_SECONDS)
            self._note_off(note)

        elif isinstance(action, SetEQ):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(EQ_CC[(action.deck, action.band)], round(clamped * 127))

        elif isinstance(action, SetVolume):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(VOLUME_CC[action.deck], round(clamped * 127))

        elif isinstance(action, HotCue):
            if not (1 <= action.cue <= 8):
                raise ValueError(f"hot cue must be 1..8, got {action.cue}")
            self._note_on(_hotcue_note(action.deck, action.cue), velocity=127)

        elif isinstance(action, Sync):
            self._note_on(SYNC_NOTES[action.deck], velocity=127)

        elif isinstance(action, LoadTrack):
            self._dispatch_load_track(action)

        else:
            # FadeToDeck is composite — handled by the Executor, not here.
            raise ValueError(
                f"MidiAdapter received non-atomic action: {action!r}. "
                "Use Executor.run_plan() for composite actions like FadeToDeck."
            )

    # --- LoadTrack dispatch (non-MIDI, see D-015) ---

    def _dispatch_load_track(self, action: LoadTrack) -> None:
        """LoadTrack is intentionally not auto-dispatched.

        We investigated three load paths and rejected them all (see
        DECISIONS § D-015):
          - `open -a Mixxx <file>`: Mixxx 2.5/2.6 ignore open events
            for already-running instances.
          - Mixxx 2.6 controller API: still no path-based load — only
            UI-selected load.
          - Library navigation via MIDI: works but is fragile to any
            user click in Mixxx's library pane.

        Instead the dashboard intercepts plans containing LoadTrack and
        renders a 'Suggested track' card (the LLM's library reasoning
        IS the deliverable). The exception below carries the resolved
        Track so the dashboard can build the card without re-querying
        the library.
        """
        if self._library is None:
            raise LoadTrackSuggestion(action=action, track=None)
        track = self._library.get_by_id(action.track_id)
        raise LoadTrackSuggestion(action=action, track=track)

    # --- low-level MIDI helpers ---

    def _note_on(self, note: int, velocity: int = 127) -> None:
        self._midi_out.send_message([NOTE_ON, note, velocity])

    def _note_off(self, note: int) -> None:
        self._midi_out.send_message([NOTE_ON, note, 0])

    def _cc(self, controller: int, value: int) -> None:
        self._midi_out.send_message([CONTROL_CHANGE, controller, value])
