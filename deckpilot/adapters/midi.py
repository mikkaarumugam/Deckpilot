"""
MidiAdapter — turns DJActions into MIDI messages and ships them through a
virtual MIDI port (the macOS IAC Driver). The receiving DJ software (Mixxx
in our setup) has been told which MIDI note means what by the mapping file
at adapters/mappings/mixxx.midi.xml.

Design:
- The adapter only handles ATOMIC actions — one DJAction → one MIDI message
  (or a brief on/off pair for nudge). Time-based actions like FadeToDeck are
  decomposed into a stream of atomic actions by the Executor (see
  core/executor.py).
- The note/CC numbers live in module-level constants below. They MUST match
  the numbers in the Mixxx mapping XML. If you change one, change the other.
"""

from __future__ import annotations

import time

import rtmidi

from deckpilot.adapters.base import Adapter
from deckpilot.core.actions import (
    DJAction,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)


# --- MIDI status bytes (all on channel 1; lower nibble is the channel - 1) ---
NOTE_ON = 0x90
NOTE_OFF = 0x80
CONTROL_CHANGE = 0xB0


# --- Note/CC numbers — keep in sync with mixxx.midi.xml ---
# Play and pause have separate notes (60/62 = play, 61/63 = pause) so each
# intent maps to a unique MIDI message — see mixxx.midi.js for why.
PLAY_NOTES = {1: 0x3C, 2: 0x3E}
PAUSE_NOTES = {1: 0x3D, 2: 0x3F}
CROSSFADER_CC = 0x14                            # CC 20
LOOP_NOTES = {1: 0x46, 2: 0x47}                 # toggle 8-beat loop
NUDGE_NOTES = {
    (1, "forward"): 0x50,
    (1, "back"): 0x51,
    (2, "forward"): 0x52,
    (2, "back"): 0x53,
}

# How long to "hold" a nudge button before releasing it.
# Mixxx's rate_temp_up nudges while held — 100ms feels like a quick tap.
NUDGE_HOLD_SECONDS = 0.1

DEFAULT_PORT_NAME = "IAC Driver Bus 1"


class MidiAdapter(Adapter):
    """Dispatches atomic DJActions as MIDI messages."""

    def __init__(self, port_name: str = DEFAULT_PORT_NAME) -> None:
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

    @property
    def port_name(self) -> str:
        return self._port_name

    def dispatch(self, action: DJAction) -> None:
        """Execute one atomic action by sending the corresponding MIDI message(s)."""
        if isinstance(action, PlayDeck):
            # Hits DeckPilot.playDeck{N} in mixxx.midi.js, which sets play=1.
            self._note_on(PLAY_NOTES[action.deck], velocity=127)

        elif isinstance(action, PauseDeck):
            # Hits DeckPilot.pauseDeck{N} in mixxx.midi.js, which sets play=0.
            self._note_on(PAUSE_NOTES[action.deck], velocity=127)

        elif isinstance(action, SetCrossfader):
            # Clamp to [0, 1] then scale to [0, 127] for MIDI CC.
            clamped = max(0.0, min(1.0, action.value))
            self._cc(CROSSFADER_CC, round(clamped * 127))

        elif isinstance(action, LoopDeck):
            # Toggle an 8-beat loop. Variable beat counts are TODO — would
            # require a second binding for `beatloop_size` and dispatching
            # both CC + note here.
            self._note_on(LOOP_NOTES[action.deck], velocity=127)

        elif isinstance(action, NudgeDeck):
            # Mixxx's rate_temp_up/down is a "while held" button.
            # Tap = press, brief wait, release.
            note = NUDGE_NOTES[(action.deck, action.direction)]
            self._note_on(note, velocity=127)
            time.sleep(NUDGE_HOLD_SECONDS)
            self._note_off(note)

        else:
            # FadeToDeck is composite — should be handled by the Executor, not here.
            raise ValueError(
                f"MidiAdapter received non-atomic action: {action!r}. "
                "Use Executor.run() to dispatch composite actions like FadeToDeck."
            )

    # --- low-level MIDI helpers ---

    def _note_on(self, note: int, velocity: int = 127) -> None:
        self._midi_out.send_message([NOTE_ON, note, velocity])

    def _note_off(self, note: int) -> None:
        # We send "note_on with velocity 0" rather than an explicit 0x80
        # note_off. Reason: Mixxx's <normal/> bindings are tied to a specific
        # status byte. Our mapping uses 0x90 (note_on), so we have to keep
        # using 0x90 — velocity 0 still gets read as "control value = 0",
        # which Mixxx's `play` setter interprets as "pause."
        # Both forms are valid per the MIDI spec; this one matches our binding.
        self._midi_out.send_message([NOTE_ON, note, 0])

    def _cc(self, controller: int, value: int) -> None:
        self._midi_out.send_message([CONTROL_CHANGE, controller, value])
