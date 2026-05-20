"""
Sanity check for the MIDI pipeline. Run this BEFORE anything else.

What it does:
    1. Lists all MIDI output ports your Mac can see.
    2. If an IAC port is available, opens it and sends a play→pause pulse
       on deck 1 (note 60: note_on for 3 seconds, then note_off).
    3. Tells you what to do next.

Prereqs (one-time setup):
    - Audio MIDI Setup → IAC Driver → "Device is online" with at least Bus 1.
    - Mixxx running with the DeckPilot mapping loaded on IAC Driver Bus 1.
    - A track loaded on Deck 1, paused.

Run:
    python scripts/send_test_note.py

Expected: deck 1 plays for 3 seconds, then pauses. If you see that, the
whole pipeline works end-to-end (Python → IAC → Mixxx → audio).
"""

from __future__ import annotations

import time

import rtmidi


PLAY_NOTE = 60       # matches PLAY_NOTES[1] in deckpilot/adapters/midi.py
PAUSE_NOTE = 61      # matches PAUSE_NOTES[1]
HOLD_SECONDS = 3.0   # how long to play before sending pause


def main() -> int:
    midi_out = rtmidi.MidiOut()
    ports = midi_out.get_ports()

    print("Available MIDI output ports:")
    if not ports:
        print("  (none found)")
        print()
        print("Enable the IAC Driver in Audio MIDI Setup and try again.")
        return 1

    for i, name in enumerate(ports):
        print(f"  [{i}] {name}")

    iac_index = next(
        (i for i, name in enumerate(ports) if "IAC" in name or "Bus" in name),
        None,
    )
    if iac_index is None:
        print()
        print("No IAC port found. Enable IAC Driver in Audio MIDI Setup.")
        return 1

    print()
    print(f"Opening port [{iac_index}] {ports[iac_index]!r}...")
    midi_out.open_port(iac_index)

    # Send the "play deck 1" note — Mixxx JS sets [Channel1].play = 1.
    print(f"Sending note_on  ch=1 note={PLAY_NOTE}  (play deck 1)")
    midi_out.send_message([0x90, PLAY_NOTE, 127])

    print(f"Holding for {HOLD_SECONDS} seconds...")
    time.sleep(HOLD_SECONDS)

    # Send the "pause deck 1" note — Mixxx JS sets [Channel1].play = 0.
    print(f"Sending note_on  ch=1 note={PAUSE_NOTE}  (pause deck 1)")
    midi_out.send_message([0x90, PAUSE_NOTE, 127])

    print()
    print("Done. If Mixxx played deck 1 for ~3 seconds then paused, the")
    print("MIDI pipeline works end-to-end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
