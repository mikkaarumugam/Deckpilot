"""
Sanity check for the MIDI pipeline. Run this BEFORE anything else.

What it does:
    1. Lists all MIDI output ports your Mac can see.
    2. If an IAC port is available, opens it and sends a single middle-C note.
    3. Tells you what to do next.

Prereqs (one-time setup):
    - Open "Audio MIDI Setup" (Spotlight: "Audio MIDI Setup").
    - Window → Show MIDI Studio.
    - Double-click "IAC Driver".
    - Check "Device is online".
    - Make sure at least one port (e.g. "Bus 1") is listed.
    - Hit Apply.

Then run:
    python scripts/send_test_note.py

Expected output: a list of ports, and a confirmation that we sent note 60.
If VirtualDJ is open and has a control MIDI-Learned to channel 1 note 60, it
should react.
"""

from __future__ import annotations

import time

import rtmidi


def main() -> int:
    midiout = rtmidi.MidiOut()
    ports = midiout.get_ports()

    print("Available MIDI output ports:")
    if not ports:
        print("  (none found)")
        print()
        print("Enable the IAC Driver in Audio MIDI Setup and try again.")
        return 1

    for i, name in enumerate(ports):
        print(f"  [{i}] {name}")

    # Pick the first port that looks like IAC.
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
    midiout.open_port(iac_index)

    # Send note 60 (middle C), channel 1, velocity 127.
    # In MIDI, channel 1 = status byte 0x90 for note_on.
    note_on = [0x90, 60, 127]
    note_off = [0x80, 60, 0]

    print("Sending note_on  ch=1 note=60 velocity=127")
    midiout.send_message(note_on)
    time.sleep(0.5)

    print("Sending note_off ch=1 note=60")
    midiout.send_message(note_off)

    print()
    print("Done. If VirtualDJ is open and has a control MIDI-Learned to")
    print("channel 1 note 60, it should have just reacted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
