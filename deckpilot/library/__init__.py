"""Library awareness: read-only access to Mixxx's track database.

Distinct from the agent layer (control planning over time) — this is
about *content choice*: which track to load, by name/artist/BPM/genre.
"""

from deckpilot.library.reader import LibraryReader, Track

__all__ = ["LibraryReader", "Track"]
