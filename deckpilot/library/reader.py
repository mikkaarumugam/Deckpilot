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

    def find_by_bpm(
        self,
        low: float,
        high: float,
        duration: float | None = None,
        duration_tolerance: float = 2.0,
    ) -> list[Track]:
        """Tracks whose analysed BPM falls in [low, high]. Skips
        un-analysed tracks (bpm = 0).

        Optional `duration` narrows further by track length (seconds);
        only tracks within ±`duration_tolerance` are kept. Used by
        /state to disambiguate when BPM matching alone returns multiple
        candidates (common in dense BPM zones — 120, 90, 140). 2-second
        tolerance handles small mismatches between MixxxFeedback's
        14-bit integer encoding and the library's full-precision float.
        """
        results = self._query(
            "library.bpm BETWEEN ? AND ? AND library.bpm > 0",
            (low, high),
        )
        if duration is not None and duration > 0:
            results = [
                t for t in results
                if abs(t.duration - duration) <= duration_tolerance
            ]
        return results

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

    def get_artwork(self, track_id: int) -> tuple[bytes, str] | None:
        """Read embedded album art from a track's audio file.

        Returns (image_bytes, mime_type) on success, None when the file
        has no embedded art OR can't be opened (deleted, codec issue).
        We deliberately don't fall back to anywhere else — the caller
        renders a placeholder for the None case.

        mutagen handles all the audio formats Mixxx supports (MP3 via
        ID3, M4A via MP4, FLAC, OGG). Each container stores artwork
        differently, so the branching below normalizes the result.
        """
        track = self.get_by_id(track_id)
        if track is None or not track.location:
            return None

        # Local import: mutagen is only needed for this path, no point
        # adding it to top-level import time for callers that never use it.
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            return None

        try:
            audio = MutagenFile(track.location)
        except Exception:
            # File deleted, malformed, or codec unsupported — caller
            # gets None and renders the no-art placeholder.
            return None
        if audio is None:
            return None

        # MP3 / ID3: artwork lives in APIC frames keyed like "APIC:" or
        # "APIC:Cover (front)". Take the first one we find.
        if hasattr(audio, "tags") and audio.tags is not None:
            for key in audio.tags.keys():
                if key.startswith("APIC"):
                    apic = audio.tags[key]
                    return (apic.data, apic.mime or "image/jpeg")

        # MP4 / M4A: artwork lives in the "covr" atom as a list of
        # MP4Cover objects. imageformat tells us PNG vs JPEG.
        if hasattr(audio, "tags") and audio.tags is not None:
            covers = audio.tags.get("covr")
            if covers:
                cover = covers[0]
                # mutagen MP4Cover.FORMAT_PNG = 14, FORMAT_JPEG = 13
                mime = "image/png" if cover.imageformat == 14 else "image/jpeg"
                return (bytes(cover), mime)

        # FLAC / OGG: pictures are on audio.pictures, not in tags.
        if hasattr(audio, "pictures") and audio.pictures:
            pic = audio.pictures[0]
            return (pic.data, pic.mime or "image/jpeg")

        return None

    def count_search_matches(self, query: str) -> int:
        """Approximate how many rows Mixxx's library search would show
        for `query`. Used by the GUI auto-load path (D-019) as a
        uniqueness check before firing GUI automation — if more than
        one row matches, we fall back to the manual-drag suggestion
        card rather than risk loading the wrong track.

        Conservative approximation: each space-separated token must
        appear (case-insensitive substring) in either the title or
        the artist. Mixxx's actual search also covers album / comment
        / genre, so a `1` here doesn't *guarantee* Mixxx will show
        exactly 1 row — but in practice it's accurate enough for
        typical "Title Artist" queries.
        """
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return 0

        conditions = []
        params: list[str] = []
        for t in tokens:
            conditions.append(
                "(LOWER(library.title) LIKE ? OR LOWER(library.artist) LIKE ?)"
            )
            params.extend([f"%{t}%", f"%{t}%"])

        where = " AND ".join(conditions)
        sql = f"""
            SELECT COUNT(*) FROM library
            JOIN track_locations ON library.location = track_locations.id
            WHERE library.mixxx_deleted = 0
              AND track_locations.fs_deleted = 0
              AND {where}
        """
        with self._connect() as conn:
            return conn.execute(sql, tuple(params)).fetchone()[0]
