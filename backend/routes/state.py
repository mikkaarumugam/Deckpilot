"""GET /state — live snapshot of both decks.

Sources:
- Play state + BPM: MixxxFeedback (MIDI feedback from Mixxx).
- Track identity: library lookup against the live BPM (the same heuristic
  the Streamlit dashboard uses today — see docs/DECISIONS.md § D-017).

Polled by the frontend at 250ms during runs. When the feedback isn't
available (Mixxx not running / IAC not enabled), returns empty decks
rather than 5xx — degraded UX is better than a crashed dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models import (
    DeckStatePayload,
    ProgressPayload,
    StateResponse,
    TrackPayload,
)
from ..services.singletons import get_feedback, get_library

router = APIRouter()


# Tight enough that the matched BPM CC value's ±0.5 BPM rounding error doesn't
# pick up an adjacent library track. See D-017.
_BPM_MATCH_TOLERANCE = 0.6


def _format_mmss(seconds: float) -> str:
    """Format a duration in seconds as `m:ss` (e.g. 0:32, 4:01).
    Returns `—` for negatives or unknowns so the UI hides it."""
    if seconds <= 0:
        return "—"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


@router.get("/state", response_model=StateResponse)
def state() -> StateResponse:
    feedback = get_feedback()
    library = get_library()

    if feedback is None:
        return StateResponse(
            decks=[
                DeckStatePayload(n=1, status="cued", bpm=0.0),
                DeckStatePayload(n=2, status="cued", bpm=0.0),
            ],
        )

    snap = feedback.snapshot()
    decks: list[DeckStatePayload] = []
    bpms: list[float] = []
    for n in (1, 2):
        d = snap.deck(n)
        track_payload: TrackPayload | None = None
        track_duration = 0.0  # seconds; from library if we got a unique match
        if library is not None and d.bpm > 0:
            candidates = library.find_by_bpm(
                d.bpm - _BPM_MATCH_TOLERANCE,
                d.bpm + _BPM_MATCH_TOLERANCE,
            )
            if len(candidates) == 1:
                t = candidates[0]
                track_duration = t.duration
                track_payload = TrackPayload(
                    id=t.id,
                    artist=t.artist,
                    title=t.title,
                    bpm=t.bpm,
                    key=t.key,
                    genre=t.genre,
                )

        # Compose progress from the MIDI position read-back. When we know
        # the track's duration (resolved via BPM lookup) we can also render
        # m:ss timestamps; otherwise just the percentage for the bar.
        if track_duration > 0:
            elapsed = d.position * track_duration
            progress = ProgressPayload(
                t=_format_mmss(elapsed),
                total=_format_mmss(track_duration),
                pct=d.position * 100.0,
            )
        elif d.position > 0:
            progress = ProgressPayload(
                t="—", total="—", pct=d.position * 100.0,
            )
        else:
            progress = ProgressPayload()

        decks.append(
            DeckStatePayload(
                n=n,  # type: ignore[arg-type]
                status="playing" if d.playing else "paused",
                bpm=d.bpm,
                track=track_payload,
                progress=progress,
            )
        )
        bpms.append(d.bpm)

    bpm_delta = None
    if all(b > 0 for b in bpms):
        bpm_delta = bpms[1] - bpms[0]

    return StateResponse(decks=decks, bpm_delta=bpm_delta)
