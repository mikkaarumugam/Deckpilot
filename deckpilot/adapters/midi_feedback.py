"""MixxxFeedback — opens IAC Bus 1 as a MIDI INPUT and parses messages
Mixxx emits via the output bindings in mixxx.midi.xml + mixxx.midi.js.

Wire format (must match the mapping):
  - NOTE 0x10 / 0x11  → deck 1 / deck 2 play state.
      status 0x90 with velocity > 0  = playing
      status 0x80 (note_off)         = paused
      (Mixxx may send either form for "off"; we treat both as paused.)
  - CC 0x30 / 0x31    → deck 1 / deck 2 BPM, scaled BPM_MIN..BPM_MAX → 0..127.

Threading note: python-rtmidi delivers messages on its own callback
thread. We guard state mutation with a Lock so the dashboard can read
a consistent snapshot.
"""

from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass, field, replace
from typing import Callable

import rtmidi

# Must match deckpilot/adapters/mappings/mixxx.midi.js BPM_MIN / BPM_MAX.
BPM_MIN = 60.0
BPM_MAX = 200.0

# Must match the <output> bindings + JS sendBpm CCs.
PLAY_STATE_NOTE = {0x10: 1, 0x11: 2}   # note → deck number
BPM_CC = {0x30: 1, 0x31: 2}            # cc   → deck number

DEFAULT_PORT_NAME = "IAC Driver Bus 1"


@dataclass(frozen=True)
class DeckState:
    """Snapshot of one deck's state as inferred from Mixxx feedback."""
    playing: bool = False
    bpm: float = 0.0  # 0.0 = unknown / no track loaded yet


@dataclass(frozen=True)
class MixxxState:
    """All decks. Frozen so consumers can't mutate a returned snapshot."""
    decks: dict[int, DeckState] = field(default_factory=dict)

    def deck(self, n: int) -> DeckState:
        return self.decks.get(n, DeckState())


class MixxxFeedback:
    """Subscribes to Mixxx's MIDI output and maintains a state snapshot.

    Typical use:
        fb = MixxxFeedback().start()
        ...
        state = fb.snapshot()        # returns an immutable MixxxState
        d1 = state.deck(1)           # DeckState(playing=True, bpm=121.3)
        ...
        fb.stop()

    Safe if Mixxx isn't running or the port doesn't exist — start() will
    raise; callers in the dashboard should catch and degrade gracefully.
    """

    def __init__(self, port_name: str = DEFAULT_PORT_NAME) -> None:
        self._port_name = port_name
        self._midi_in: rtmidi.MidiIn | None = None
        self._lock = threading.Lock()
        # Mutable internal dict; snapshot() copies it into a frozen MixxxState.
        self._decks: dict[int, DeckState] = {1: DeckState(), 2: DeckState()}
        self._on_change: Callable[[], None] | None = None

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> MixxxFeedback:
        midi_in = rtmidi.MidiIn()
        ports = midi_in.get_ports()
        try:
            idx = next(i for i, n in enumerate(ports) if self._port_name in n)
        except StopIteration as exc:
            raise RuntimeError(
                f"MIDI input port matching {self._port_name!r} not found. "
                f"Available: {ports!r}. Is IAC Driver enabled?"
            ) from exc
        midi_in.open_port(idx)
        # We never need sysex / timing clock / active sense — drop them at
        # the driver level so they don't even hit our callback.
        midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        midi_in.set_callback(self._on_message)
        self._midi_in = midi_in

        # Ensure the port closes cleanly on process exit. Without this,
        # Streamlit auto-reload + rtmidi has been observed to segfault
        # (rtmidi callback thread referencing torn-down Python state).
        atexit.register(self.stop)

        # Handshake: ask Mixxx to re-broadcast current state. Without this we
        # only see changes from now on — fine for steady-state, but the
        # dashboard would render "BPM 0" until the user does something.
        # See DeckPilot.requestState in mixxx.midi.js.
        self._request_initial_state()

        return self

    def _request_initial_state(self) -> None:
        """Fire-and-forget MIDI note that triggers the JS broadcast handler.

        We open a short-lived MidiOut rather than depending on the main
        MidiAdapter — keeps MixxxFeedback usable standalone (e.g. in tests
        or the smoke script) without dragging the executor along."""
        midi_out = rtmidi.MidiOut()
        ports = midi_out.get_ports()
        try:
            idx = next(i for i, n in enumerate(ports) if self._port_name in n)
        except StopIteration:
            return  # Mixxx will keep us in the dark; not fatal.
        midi_out.open_port(idx)
        try:
            midi_out.send_message([0x90, 0x7F, 0x7F])  # request-state trigger
        finally:
            midi_out.close_port()

    def stop(self) -> None:
        if self._midi_in is not None:
            try:
                # Cancel the callback first so no new messages can land on
                # a port we're about to close — closes the race window
                # that's caused the segfault we saw.
                self._midi_in.cancel_callback()
                self._midi_in.close_port()
            except Exception:
                pass
            self._midi_in = None

    # ── state access ─────────────────────────────────────────────────

    def snapshot(self) -> MixxxState:
        """Thread-safe snapshot. Returns a new MixxxState every call so
        the caller can't accidentally see a torn read."""
        with self._lock:
            return MixxxState(decks=dict(self._decks))

    def set_change_callback(self, cb: Callable[[], None] | None) -> None:
        """Optional: fire `cb` after any state change. Streamlit doesn't
        re-render on background-thread mutations, so the dashboard uses
        a polling loop instead — but exposing the hook keeps options open."""
        self._on_change = cb

    # ── internals ────────────────────────────────────────────────────

    def _on_message(self, msg, _data=None) -> None:
        """Called by rtmidi on its callback thread."""
        data, _dt = msg
        if not data:
            return
        # Pad to 3 bytes so unpacking is safe even for unusual messages.
        status, d1, d2 = (data + [0, 0])[:3]
        kind = status & 0xF0
        changed = False

        if kind in (0x90, 0x80) and d1 in PLAY_STATE_NOTE:
            deck = PLAY_STATE_NOTE[d1]
            # 0x90 with velocity 0 is spec-equivalent to note_off (the
            # same gotcha that bit the send-side; see DECISIONS D-004).
            playing = (kind == 0x90 and d2 > 0)
            with self._lock:
                prev = self._decks[deck]
                if prev.playing != playing:
                    self._decks[deck] = replace(prev, playing=playing)
                    changed = True

        elif kind == 0xB0 and d1 in BPM_CC:
            deck = BPM_CC[d1]
            bpm = BPM_MIN + (d2 / 127.0) * (BPM_MAX - BPM_MIN)
            with self._lock:
                prev = self._decks[deck]
                # Avoid float-noise re-renders: only flag changed when the
                # rounded BPM moved meaningfully (>= 0.1 BPM).
                if abs(prev.bpm - bpm) >= 0.1:
                    self._decks[deck] = replace(prev, bpm=bpm)
                    changed = True

        if changed and self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                # Never let a UI-side callback kill the MIDI thread.
                pass
