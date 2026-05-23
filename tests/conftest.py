"""
Make the repo-root packages importable for tests.

`deckpilot/` is installed via pyproject's `find packages`, so
`from deckpilot.x import y` works in any context. `backend/` is NOT a
pip-installed package — it's the FastAPI app folder, run via
`uvicorn backend.main:app` which puts CWD on sys.path itself.

For pytest, we add the repo root explicitly so tests can import both
`deckpilot.*` and `backend.*` without further setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
