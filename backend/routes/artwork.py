"""GET /artwork/{track_id} — serve embedded album art.

Reads the artwork directly from the track's audio file via mutagen
(see deckpilot/library/reader.py:get_artwork). 404 when the track has
no embedded image — caller (DeckCard) renders a placeholder.

Caching: artwork is content-static per file, so we set a long
max-age. If a user updates a track's embedded image and refreshes
DeckPilot, they may need to hard-reload — acceptable trade-off vs
re-reading + re-decoding hundreds of KB on every poll.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..services.singletons import get_library

router = APIRouter()


@router.get("/artwork/{track_id}")
def artwork(track_id: int) -> Response:
    library = get_library()
    if library is None:
        raise HTTPException(status_code=503, detail="library unavailable")

    art = library.get_artwork(track_id)
    if art is None:
        raise HTTPException(status_code=404, detail="no artwork for track")

    data, mime = art
    return Response(
        content=data,
        media_type=mime,
        headers={
            # Embedded art doesn't change in practice. Cache aggressively;
            # hard-refresh will bust it if a user does re-embed.
            "Cache-Control": "public, max-age=86400",
        },
    )
