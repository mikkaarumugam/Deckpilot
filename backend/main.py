"""DeckPilot FastAPI app.

Wires up the five routes (parse, execute, state, undo, reset) + CORS
for the Vite dev server origin + a lifespan handler that cleans up the
MixxxFeedback callback thread on shutdown.

Run with:

    source .venv/bin/activate
    uvicorn backend.main:app --reload --port 8000

For prod / demo recording:

    uvicorn backend.main:app --port 8000

CORS is wide-open in dev. Tighten before shipping to a multi-user setup
(not on the roadmap — DeckPilot is local-only by design).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import execute as execute_routes
from .routes import parse as parse_routes
from .routes import parse_stream as parse_stream_routes
from .routes import reset as reset_routes
from .routes import state as state_routes
from .routes import undo as undo_routes
from .services.singletons import stop_feedback


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: nothing to eagerly init — all singletons are lazy.
    yield
    # Shutdown: MixxxFeedback holds a callback thread that MUST be torn
    # down explicitly to avoid the rtmidi segfault gotcha. See
    # docs/GOTCHAS.md and D-016.
    stop_feedback()


app = FastAPI(
    title="DeckPilot",
    version="0.2.0",
    description=(
        "HTTP wrapper around the existing deckpilot/ Python package. "
        "See docs/MIGRATION.md and DECISIONS.md § D-018 for the why."
    ),
    lifespan=lifespan,
)

# CORS — only the Vite dev origin is needed in development. If you run the
# built frontend on a different port or origin, add it here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parse_routes.router)
app.include_router(parse_stream_routes.router)
app.include_router(execute_routes.router)
app.include_router(state_routes.router)
app.include_router(undo_routes.router)
app.include_router(reset_routes.router)


@app.get("/")
def root():
    return {
        "name": "DeckPilot",
        "version": "0.2.0",
        "endpoints": [
            "/parse",
            "/parse/stream",
            "/execute",
            "/state",
            "/undo",
            "/reset",
        ],
    }
