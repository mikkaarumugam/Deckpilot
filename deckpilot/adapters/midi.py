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
    LOOP_BEAT_SIZES,
    DJAction,
    EjectDeck,
    HotCue,
    LoadTrack,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
    SetEQ,
    SetFilter,
    SetFx,
    SetPitch,
    SetVolume,
    Sync,
)

if TYPE_CHECKING:
    from deckpilot.adapters.gui import MixxxGuiAdapter
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

# Eject (direct `eject` control binding in Mixxx — momentary button).
EJECT_NOTES = {1: 0x56, 2: 0x57}    # 86, 87

# Crossfader (CC 20).
CROSSFADER_CC = 0x14

# Loop toggles, one per (deck, beats). Mirror in mixxx.midi.xml — both files
# share this allocation. Toggle: re-firing the same note ends the loop.
# Firing a different size while a loop is active replaces it.
#   deck 1: 0x40..0x45 for sizes 1, 2, 4, 8, 16, 32
#   deck 2: 0x48..0x4D for sizes 1, 2, 4, 8, 16, 32
LOOP_NOTES: dict[tuple[int, int], int] = {
    (1, 1):  0x40, (1, 2):  0x41, (1, 4):  0x42,
    (1, 8):  0x43, (1, 16): 0x44, (1, 32): 0x45,
    (2, 1):  0x48, (2, 2):  0x49, (2, 4):  0x4A,
    (2, 8):  0x4B, (2, 16): 0x4C, (2, 32): 0x4D,
}

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

# Filter knob per deck (CC 36, 37). Maps to QuickEffectRack super1: 0.5 = bypass.
FILTER_CC = {1: 0x24, 2: 0x25}

# Pitch slider per deck (CC 38, 39). Script-bound — JS handler does bipolar
# scaling so CC 64 = rate 0.0 (no pitch shift).
PITCH_CC = {1: 0x26, 2: 0x27}

# FX wet per (deck, unit) (CC 52..55). Script-bound — JS handler toggles
# the deck's assignment on the unit AND sets the unit's mix knob.
FX_CC: dict[tuple[int, int], int] = {
    (1, 1): 0x34, (1, 2): 0x35,
    (2, 1): 0x36, (2, 2): 0x37,
}

DEFAULT_PORT_NAME = "IAC Driver Bus 1"


class MidiAdapter(Adapter):
    """Dispatches atomic DJActions as MIDI messages.

    `library` is optional: needed to (a) resolve LoadTrack ids to
    Track records and (b) run the uniqueness check before delegating
    to the GUI adapter. Without it, LoadTrack falls back to the
    suggestion-card path.

    `gui` is also optional: when present AND the library uniqueness
    check passes, LoadTrack actions execute via the GUI adapter
    (Mixxx search-box automation, see D-019). When absent, LoadTrack
    falls back to LoadTrackSuggestion so the dashboard can render a
    "drag this manually" card (the D-015 behavior).
    """

    def __init__(
        self,
        port_name: str = DEFAULT_PORT_NAME,
        library: "LibraryReader | None" = None,
        gui: "MixxxGuiAdapter | None" = None,
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
        self._gui = gui

    @property
    def port_name(self) -> str:
        return self._port_name

    def dispatch(self, action: DJAction) -> None:
        """Execute one atomic action by sending the corresponding MIDI message(s)."""
        if isinstance(action, PlayDeck):
            self._note_on(PLAY_NOTES[action.deck], velocity=127)

        elif isinstance(action, PauseDeck):
            self._note_on(PAUSE_NOTES[action.deck], velocity=127)

        elif isinstance(action, EjectDeck):
            self._note_on(EJECT_NOTES[action.deck], velocity=127)

        elif isinstance(action, SetCrossfader):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(CROSSFADER_CC, round(clamped * 127))

        elif isinstance(action, LoopDeck):
            if action.beats not in LOOP_BEAT_SIZES:
                raise ValueError(
                    f"loop beats must be one of {LOOP_BEAT_SIZES}, "
                    f"got {action.beats}"
                )
            self._note_on(LOOP_NOTES[(action.deck, action.beats)], velocity=127)

        elif isinstance(action, NudgeDeck):
            note = NUDGE_NOTES[(action.deck, action.direction)]
            self._note_on(note, velocity=127)
            time.sleep(NUDGE_HOLD_SECONDS)
            self._note_off(note)

        elif isinstance(action, SetEQ):
            # Mixxx's EQ control range is 0..4 and the default skin renders
            # the rotary linearly across that range, so visual centre = 2.0
            # (technically ~+6 dB, not unity). We map value 1.0 to CC 64 →
            # Mixxx 2.0 to keep the knob visually centred after a reset or
            # bass-swap restore. The audible boost is the trade-off; in
            # practice a centred knob is the stronger UX signal for "back
            # to neutral" than audibly-flat-but-visibly-off-centre.
            clamped = max(0.0, min(1.0, action.value))
            self._cc(EQ_CC[(action.deck, action.band)], round(clamped * 64))

        elif isinstance(action, SetVolume):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(VOLUME_CC[action.deck], round(clamped * 127))

        elif isinstance(action, HotCue):
            if not (1 <= action.cue <= 8):
                raise ValueError(f"hot cue must be 1..8, got {action.cue}")
            self._note_on(_hotcue_note(action.deck, action.cue), velocity=127)

        elif isinstance(action, Sync):
            self._note_on(SYNC_NOTES[action.deck], velocity=127)

        elif isinstance(action, SetFilter):
            clamped = max(0.0, min(1.0, action.value))
            self._cc(FILTER_CC[action.deck], round(clamped * 127))

        elif isinstance(action, SetFx):
            if action.unit not in (1, 2):
                raise ValueError(f"fx unit must be 1 or 2, got {action.unit}")
            clamped = max(0.0, min(1.0, action.value))
            self._cc(FX_CC[(action.deck, action.unit)], round(clamped * 127))

        elif isinstance(action, SetPitch):
            # Bipolar: -1..+1 → CC 0..127 with 64 = neutral (no pitch shift).
            # JS handler inverts this back to rate; keeping the math here
            # makes the Python-side action contract clean.
            clamped = max(-1.0, min(1.0, action.value))
            cc_value = 64 + round(clamped * 63)
            self._cc(PITCH_CC[action.deck], cc_value)

        elif isinstance(action, LoadTrack):
            self._dispatch_load_track(action)

        else:
            # FadeToDeck is composite — handled by the Executor, not here.
            raise ValueError(
                f"MidiAdapter received non-atomic action: {action!r}. "
                "Use Executor.run_plan() for composite actions like FadeToDeck."
            )

    # --- LoadTrack dispatch (hybrid MIDI + GUI, see D-019) ---

    def _dispatch_load_track(self, action: LoadTrack) -> None:
        """LoadTrack is the one action MIDI can't reach — Mixxx's
        controller-script API has no path-based load primitive across
        versions 2.5-2.7 (see D-015). D-019 supersedes D-015: we now
        load via a GUI adapter (macOS osascript driving Mixxx's library
        search box) when one is wired in AND the chosen track is
        uniquely identifiable from its title+artist. Otherwise we fall
        back to LoadTrackSuggestion so the dashboard renders a
        manual-drag card (the original D-015 behaviour).

        The uniqueness check is a guard against destructive misfires:
        if the LLM picks a track whose title+artist matches multiple
        rows in the library, GUI search would filter to >1 row and
        Shift+Right would load the wrong one. Conservative fallback
        > silent error.
        """
        if self._library is None:
            # No library → can't resolve track or build search query.
            raise LoadTrackSuggestion(action=action, track=None)

        track = self._library.get_by_id(action.track_id)
        if track is None:
            raise LoadTrackSuggestion(action=action, track=None)

        if self._gui is None:
            # No GUI adapter wired → fall back to the suggestion card.
            raise LoadTrackSuggestion(action=action, track=track)

        query = f"{track.title} {track.artist}".strip()
        if self._library.count_search_matches(query) != 1:
            # Ambiguous — multiple library rows match this query; GUI
            # search would risk loading the wrong row. Defer to user.
            raise LoadTrackSuggestion(action=action, track=track)

        # Fire the GUI load. Blocks until Mixxx has loaded the track
        # so any subsequent step in the plan (e.g. PlayDeck) fires at
        # the right moment without manual scheduling. Pass track_id so
        # the GUI adapter can remember the deck→id mapping for the
        # /state route's tie-breaker when BPM matching is ambiguous.
        self._gui.load_track(deck=action.deck, query=query, track_id=track.id)

    # --- low-level MIDI helpers ---

    def _note_on(self, note: int, velocity: int = 127) -> None:
        self._midi_out.send_message([NOTE_ON, note, velocity])

    def _note_off(self, note: int) -> None:
        self._midi_out.send_message([NOTE_ON, note, 0])

    def _cc(self, controller: int, value: int) -> None:
        self._midi_out.send_message([CONTROL_CHANGE, controller, value])
