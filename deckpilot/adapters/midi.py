"""
MidiAdapter: dispatch DJActions as MIDI messages through a virtual MIDI port
(macOS IAC Driver, typically). The receiving DJ software (VirtualDJ, Mixxx, ...)
has been MIDI-Learned to respond to the notes/CCs we send.

The mapping (which note triggers which action) lives in
adapters/mappings/virtualdj.json so it can be edited without code changes.

Filled in for real in M2.
"""

from __future__ import annotations

# TODO(M2):
#   class MidiAdapter(Adapter):
#       def __init__(self, port_name: str, mapping_path: Path): ...
#       def dispatch(self, action: DJAction) -> None: ...
