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
from ..services.singletons import get_feedback, get_gui_adapter, get_library

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
    gui = get_gui_adapter()

    if feedback is None:
        return StateResponse(
            decks=[
                DeckStatePayload(n=1, status="cued", bpm=0.0, beat_count=0),
                DeckStatePayload(n=2, status="cued", bpm=0.0, beat_count=0),
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
            # Pass duration when we have it — narrows from "tracks at
            # this BPM" to "tracks at this BPM + length" which is
            # essentially unique. Falls back to BPM-only when duration
            # is unknown (track just loaded, half of the 14-bit pair
            # not yet received).
            candidates = library.find_by_bpm(
                d.bpm - _BPM_MATCH_TOLERANCE,
                d.bpm + _BPM_MATCH_TOLERANCE,
                duration=float(d.duration_seconds) if d.duration_seconds > 0 else None,
            )
            # Disambiguation strategy:
            #   1 candidate  → use it (the simple, common path).
            #   >1 candidates → fall back on the GUI adapter's
            #                   last_loaded[deck] memory. If the agent
            #                   loaded this track, that id will be in
            #                   the candidate set; pick the match.
            #   0 candidates → leave track_payload null (D-017).
            picked = None
            if len(candidates) == 1:
                picked = candidates[0]
            elif len(candidates) > 1 and gui is not None:
                last_id = gui.last_loaded(n)
                if last_id is not None:
                    for c in candidates:
                        if c.id == last_id:
                            picked = c
                            break

            if picked is not None:
                t = picked
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
                beat_count=d.beat_count,
            )
        )
        bpms.append(d.bpm)

    bpm_delta = None
    if all(b > 0 for b in bpms):
        bpm_delta = bpms[1] - bpms[0]

    # mixxx_alive: true when MixxxFeedback has received any MIDI from
    # Mixxx within its liveness timeout (~6s). Drives the header dot.
    # False if feedback never started OR Mixxx closed and the heartbeat
    # responses dried up. See MixxxFeedback.is_alive().
    mixxx_alive = feedback.is_alive()

    return StateResponse(decks=decks, bpm_delta=bpm_delta, mixxx_alive=mixxx_alive)
