"""Read-only reader for Mixxx's SQLite library DB.

We open the DB with `mode=ro&immutable=1` so we can never accidentally
write to Mixxx's live library — even a stray UPDATE would be rejected
by SQLite. Safe to use while Mixxx is running.

Schema notes (Mixxx 2.5.6):
- `library` holds the track metadata (artist, title, bpm, genre, key…).
- `library.location` is an INTEGER FK → `track_locations.id`. The actual
  file path lives in `track_locations.location` (varchar). The column
  name reuse is confusing; verified by `.schema` inspection.
- `mixxx_deleted=1` marks tracks Mixxx has hidden but not purged. We
  filter these out everywhere.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

# Default Mixxx DB path on macOS sandboxed install (App Store / cask).
# Override via LibraryReader(db_path=...) if Mixxx lives elsewhere.
DEFAULT_DB_PATH = Path.home() / (
    "Library/Containers/org.mixxx.mixxx/Data/Library/"
    "Application Support/Mixxx/mixxxdb.sqlite"
)


@dataclass(frozen=True)
class Track:
    """One row of Mixxx's library, typed.

    Frozen so it's hashable and safe to pass around. `bpm` and `key` can
    be missing/zero for tracks Mixxx hasn't analysed yet — callers that
    care about BPM (e.g. sync planning) should filter on bpm > 0.
    """

    id: int
    artist: str
    title: str
    album: str
    genre: str
    bpm: float
    key: str
    duration: float
    location: str  # absolute file path


# Columns we always want. Centralised so the SELECT and the Track
# constructor stay in lockstep — change one, change both.
_COLS = (
    "library.id, library.artist, library.title, library.album, "
    "library.genre, library.bpm, library.key, library.duration, "
    "track_locations.location"
)

_BASE_QUERY = f"""
    SELECT {_COLS}
    FROM library
    JOIN track_locations ON library.location = track_locations.id
    WHERE library.mixxx_deleted = 0
      AND track_locations.fs_deleted = 0
"""


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        id=row[0],
        artist=row[1] or "",
        title=row[2] or "",
        album=row[3] or "",
        genre=row[4] or "",
        bpm=float(row[5] or 0.0),
        key=row[6] or "",
        duration=float(row[7] or 0.0),
        location=row[8] or "",
    )


class LibraryReader:
    """Thin wrapper around the Mixxx SQLite library, read-only."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"Mixxx library DB not found at {self._db_path}. "
                "Is Mixxx installed?"
            )

    def _connect(self) -> sqlite3.Connection:
        # mode=ro: never allow writes — protects Mixxx's live library.
        # We deliberately do NOT use immutable=1 here: Mixxx adds new
        # tracks while running, and immutable=1 caches the DB state on
        # first open so new rows would never appear. Reopening per query
        # gives us a fresh view every time.
        uri = f"file:{self._db_path}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def _query(self, where: str = "", params: tuple = ()) -> list[Track]:
        sql = _BASE_QUERY + (f" AND {where}" if where else "") + " ORDER BY library.artist, library.title"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_track(r) for r in rows]

    # ── public API ────────────────────────────────────────────────────

    def list_tracks(self) -> list[Track]:
        """All non-deleted tracks, sorted by artist then title."""
        return self._query()

    def find_by_bpm(self, low: float, high: float) -> list[Track]:
        """Tracks whose analysed BPM falls in [low, high]. Skips
        un-analysed tracks (bpm = 0)."""
        return self._query(
            "library.bpm BETWEEN ? AND ? AND library.bpm > 0",
            (low, high),
        )

    def find_by_artist(self, name: str) -> list[Track]:
        """Case-insensitive substring match against the artist field."""
        return self._query(
            "LOWER(library.artist) LIKE ?",
            (f"%{name.lower()}%",),
        )

    def find_by_genre(self, name: str) -> list[Track]:
        """Case-insensitive substring match against the genre field."""
        return self._query(
            "LOWER(library.genre) LIKE ?",
            (f"%{name.lower()}%",),
        )

    def find_by_title_match(self, query: str) -> list[Track]:
        """Case-insensitive substring match against the title field."""
        return self._query(
            "LOWER(library.title) LIKE ?",
            (f"%{query.lower()}%",),
        )

    def get_by_id(self, track_id: int) -> Track | None:
        """Look up a single track by its library id, or None if missing
        / deleted. Used by future LoadTrack dispatch."""
        results = self._query("library.id = ?", (track_id,))
        return results[0] if results else None
